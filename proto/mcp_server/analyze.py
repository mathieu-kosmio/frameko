"""Analyse IA d'un document importé (mode connecté).

Pipeline ciblé :
  1. détection d'une éventuelle date de validité/expiration (LLM) ;
  2. pré-filtrage sémantique (embeddings + pgvector) des exigences attendant ce
     type de document, parmi tous les référentiels ;
  3. évaluation par lots (LLM) de chaque exigence retenue au vu du document.

Réutilise embeddings.embed_one et le client OpenAI (comme ingest.py). Conçu pour
tourner dans un thread d'arrière-plan ; le statut est suivi sur document.analysis_status.
"""

import json
import os
from datetime import date
from pathlib import Path

from mcp_server import db
from mcp_server.embeddings import embed_one, to_pgvector

TOP_N = 25        # exigences les plus pertinentes évaluées par document
EVAL_BATCH = 8    # exigences par appel LLM
VALID = {"conforme", "partiel", "non_conforme", "non_applicable"}


# ── Extraction du texte brut du document ────────────────────────────────────

def extract_text(path: Path) -> str:
    suf = path.suffix.lower()
    try:
        if suf == ".pdf":
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
        if suf in {".xlsx", ".xls"}:
            import pandas as pd
            sheets = pd.read_excel(path, dtype=str, sheet_name=None)
            return "\n".join(
                df.fillna("").astype(str).apply(lambda r: " ".join(r), axis=1).str.cat(sep="\n")
                for df in sheets.values())
        if suf in {".csv", ".tsv"}:
            import pandas as pd
            df = pd.read_csv(path, dtype=str, sep=None, engine="python").fillna("")
            return df.astype(str).apply(lambda r: " ".join(r), axis=1).str.cat(sep="\n")
        if suf in {".txt", ".md"}:
            return path.read_text(errors="ignore")
    except Exception:
        return ""
    return ""


# ── LLM ─────────────────────────────────────────────────────────────────────

def _client():
    from openai import OpenAI
    return OpenAI()


def _model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def detect_validity_date(text: str, client, model: str) -> str | None:
    if not text.strip():
        return None
    prompt = (
        "Extrais l'éventuelle date de fin de validité / d'expiration de ce document "
        "(certificat, attestation, agrément…). Réponds en JSON STRICT "
        "{\"valid_until\": \"YYYY-MM-DD\"} ou {\"valid_until\": null} si aucune date "
        "d'expiration claire.\n\n" + text[:6000]
    )
    try:
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}, temperature=0)
        v = json.loads(resp.choices[0].message.content).get("valid_until")
        if v and len(str(v)) >= 10:
            date.fromisoformat(str(v)[:10])   # valide le format
            return str(v)[:10]
    except Exception:
        pass
    return None


def _eval_batch(text: str, items: list[dict], client, model: str) -> dict:
    reqs = [{"i": i, "exigence": it["label"]} for i, it in enumerate(items)]
    prompt = (
        "Tu évalues la conformité d'une organisation à des exigences de certification, AU VU "
        "UNIQUEMENT du document fourni. Pour CHAQUE exigence, donne : un statut parmi "
        "conforme | partiel | non_conforme | non_applicable, une interprétation courte (1 phrase : "
        "ce que le document prouve ou non), une confiance entre 0 et 1. Si le document ne traite pas "
        "l'exigence, statut=non_conforme. Réponds en JSON STRICT : {\"e\": [{\"i\": <index>, "
        "\"status\": \"...\", \"interpretation\": \"...\", \"confidence\": <0-1>}, ...]}\n\n"
        "DOCUMENT :\n" + text[:8000] + "\n\nEXIGENCES :\n" + json.dumps(reqs, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0)
    data = json.loads(resp.choices[0].message.content)
    out: dict = {}
    for e in data.get("e", []):
        i = e.get("i")
        if isinstance(i, int) and 0 <= i < len(items):
            st = e.get("status") if e.get("status") in VALID else "non_conforme"
            conf = e.get("confidence")
            conf = float(conf) if isinstance(conf, (int, float)) else None
            out[i] = (st, (e.get("interpretation") or "")[:1000], conf)
    return out


def evaluate_document(doc_id: str, org_id: str, evidence_slug: str, text: str) -> None:
    """Pipeline complet, exécuté en thread d'arrière-plan."""
    model = _model()
    try:
        db.set_document_analysis(doc_id, org_id, "running")
        client = _client()
        valid_until = detect_validity_date(text, client, model)
        rows: list = []
        if text.strip():
            vec = to_pgvector(embed_one(text[:8000]))
            cands = db.evidence_candidates(evidence_slug, vec, TOP_N)
            for start in range(0, len(cands), EVAL_BATCH):
                batch = cands[start:start + EVAL_BATCH]
                res = _eval_batch(text, batch, client, model)
                for i, it in enumerate(batch):
                    if i in res:
                        st, interp, conf = res[i]
                        rows.append((it["id"], st, interp, conf))
        if rows:
            db.insert_evaluations(org_id, doc_id, rows)
        db.set_document_analysis(doc_id, org_id, "done", valid_until=valid_until)
    except Exception as exc:
        db.set_document_analysis(doc_id, org_id, "error", error=str(exc)[:500])
