"""
Ingestion d'un référentiel — logique partagée (CCCEV-isation).

Trois étapes, génériques (indépendantes du domaine), réutilisées par l'UI web
(wizard) et exploitables en CLI :

  1. extract_from_path(path)        source (.xlsx/.csv/.tsv/.pdf) → exigences
  2. propose(criteria)              rattachement au socle commun (candidats + degré suggéré)
  3. apply_framework(framework, …)  insertion validée (framework + critères + embeddings)

Aucune écriture en base avant apply_framework ; les étapes 1-2 sont en lecture seule.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import db
from .embeddings import embed_one, embed_texts, to_pgvector

DEGREES = ["equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"]
_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(.{8,})$")


# ── 1. Extraction ────────────────────────────────────────────────────────────

def extract_from_path(path: Path) -> list[dict]:
    """Détecte le format et renvoie [{reference, criterion}]. Lecture seule."""
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xls", ".csv", ".tsv"}:
        return _from_spreadsheet(path)
    if ext == ".pdf":
        return _from_pdf(path)
    raise ValueError(f"Format non supporté : {ext} (attendu .xlsx/.csv/.tsv/.pdf)")


def _from_spreadsheet(path: Path) -> list[dict]:
    import pandas as pd

    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(path, dtype=str, sep=sep)
    df = df.fillna("")
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(*aliases):
        for a in aliases:
            if a in cols:
                return cols[a]
        return None

    c_crit = pick("critère", "critere", "exigence", "label", "intitulé", "intitule")
    c_ref = pick("référence", "reference", "ref", "n°", "no", "code")
    if not c_crit:
        c_crit = max(df.columns, key=lambda c: df[c].astype(str).str.len().mean())
    rows = []
    for _, r in df.iterrows():
        label = str(r[c_crit]).strip()
        if not label:
            continue
        rows.append({"reference": (str(r[c_ref]).strip() if c_ref else "") or None, "criterion": label})
    return rows


def _from_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    rows = []
    for line in text.splitlines():
        m = _NUM_RE.match(line)
        if m:
            rows.append({"reference": m.group(1), "criterion": m.group(2).strip()})
    return rows


# ── 2. Rattachement au socle commun ──────────────────────────────────────────

def propose(criteria: list[dict], limit: int | None = None) -> list[dict]:
    """Pour chaque exigence, propose le rattachement : candidats (critères communs
    proches), précédents (exigences déjà qualifiées) et un degré suggéré dérivé du
    précédent le plus proche. Aucune écriture en base."""
    items = criteria[:limit] if limit else criteria
    labels = [c["criterion"] for c in items]
    if not labels:
        return []
    vectors = embed_texts(labels)
    out = []
    for item, vec in zip(items, vectors):
        lit = to_pgvector(vec)
        candidates = db.match_common(lit, k=5)
        precedents = db.nearest_fc(lit, k=3)
        top = candidates[0] if candidates else None
        # degré suggéré : celui du précédent le plus proche (sinon le plus prudent)
        sug_degree = precedents[0]["degree"] if precedents else "rapprocheDe"
        out.append({
            "reference": item.get("reference"),
            "criterion": item["criterion"],
            "candidates": [
                {"common_code": c["code"], "label": c["label_fr"],
                 "theme_slug": c["theme_slug"], "similarity": round(float(c["similarity"]), 3)}
                for c in candidates
            ],
            "precedents": [
                {"framework_slug": p["framework_slug"], "reference": p["reference"],
                 "label": p["label"], "common_code": p["common_code"],
                 "degree": p["degree"], "similarity": round(float(p["similarity"]), 3)}
                for p in precedents
            ],
            "suggested": {
                "common_code": top["code"] if top else None,
                "degree": sug_degree,
                "confidence": round(float(top["similarity"]), 3) if top else 0.0,
            },
        })
    return out


# ── 3. Insertion validée ─────────────────────────────────────────────────────

def validate(framework: dict, proposals: list[dict]) -> list[str]:
    """Contrôle les garde-fous avant écriture. Renvoie la liste des erreurs."""
    errors = []
    if not framework.get("slug"):
        errors.append("framework.slug requis")
    if not framework.get("title"):
        errors.append("framework.title requis")
    if not proposals:
        errors.append("aucune proposition")
    known = {r["code"] for r in db.query("select code from common_criterion")}
    for i, p in enumerate(proposals, 1):
        sug = p.get("suggested") or {}
        if not sug.get("common_code"):
            errors.append(f"#{i} ({p.get('reference')}): critère commun manquant")
        elif sug["common_code"] not in known:
            errors.append(f"#{i} ({p.get('reference')}): critère commun inconnu ({sug['common_code']})")
        if sug.get("degree") not in DEGREES:
            errors.append(f"#{i} ({p.get('reference')}): degré invalide ({sug.get('degree')!r})")
    return errors


# ── 4. Révision assistée des rattachements (LLM) ─────────────────────────────
# Le rattachement initial prend le top candidat sémantique + le degré du précédent
# le plus proche. Pour fiabiliser (surtout en cross-langue EN→FR), un passage LLM
# choisit LE critère commun parmi les candidats et le degré le plus juste.

def llm_choose(criterion: str, candidates: list[dict], precedents: list[dict],
               model: str | None = None) -> dict:
    """Demande au modèle OpenAI de choisir le critère commun (parmi les candidats)
    et le degré. Retourne {common_code, degree, confidence, justification}."""
    from openai import OpenAI

    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI()
    cand_txt = "\n".join(f"- {c['code']} : {c['label_fr']}" for c in candidates)
    prec_txt = "\n".join(
        f"- « {p['label'][:90]} » → {p['common_code']} (degré {p['degree']})" for p in precedents
    )
    prompt = (
        "Tu rattaches une exigence d'un référentiel de certification à un socle commun.\n\n"
        f"EXIGENCE :\n{criterion}\n\n"
        f"CRITÈRES COMMUNS CANDIDATS :\n{cand_txt}\n\n"
        f"PRÉCÉDENTS (exigences proches déjà qualifiées) :\n{prec_txt}\n\n"
        "Choisis LE critère commun le plus adapté parmi les candidats (son code), et le degré "
        f"de rapprochement parmi {DEGREES} :\n"
        "- equivautA : couvre la même exigence à l'identique\n"
        "- plusStrictQue : l'exigence est plus précise/exigeante que le critère commun\n"
        "- plusLargeQue : l'exigence couvre un périmètre plus large\n"
        "- rapprocheDe : proche mais ni équivalent ni strictement comparable\n\n"
        'Réponds en JSON strict : {"common_code": "...", "degree": "...", "confidence": 0.0-1.0, "justification": "..."}'
    )
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0,
    )
    import json
    out = json.loads(resp.choices[0].message.content)
    valid = {c["code"] for c in candidates}
    if out.get("common_code") not in valid:
        out["common_code"] = candidates[0]["code"]
        out["_note"] = "code hors candidats → repli sur le plus proche"
    if out.get("degree") not in DEGREES:
        out["degree"] = "rapprocheDe"
    return out


def translate_texts(texts: list[str], source_hint: str = "", batch: int = 8,
                    model: str | None = None) -> list[str]:
    """Traduit une liste de textes en français via OpenAI, en préservant termes
    techniques, sigles, codes et unités. Robuste : sur lot en échec (JSON tronqué,
    nombre d'éléments incohérent), repli item par item ; un item irrécupérable
    conserve son texte d'origine. Retourne la liste (même ordre, même longueur)."""
    import json
    from openai import OpenAI

    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI()

    def _run(chunk: list[str]) -> list[str] | None:
        """Traduit un lot ; renvoie None si la réponse est invalide ou désalignée."""
        prompt = (
            "Traduis en français chaque élément du tableau JSON ci-dessous (exigences / "
            "critères de certification" + (f", source : {source_hint}" if source_hint else "") + "). "
            "Préserve les termes techniques, sigles, codes, références et unités ; ne reformule pas, "
            "n'ajoute aucun commentaire. Si un élément est déjà en français, renvoie-le tel quel. "
            'Réponds en JSON STRICT : {"t": ["...", ...]} avec EXACTEMENT le même nombre d\'éléments '
            "et le même ordre.\n\n" + json.dumps(chunk, ensure_ascii=False)
        )
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}, temperature=0, max_tokens=8000)
            arr = json.loads(resp.choices[0].message.content).get("t", [])
        except Exception:
            return None
        return arr if len(arr) == len(chunk) else None

    out: list[str] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        arr = _run(chunk)
        if arr is None:  # repli item par item, en conservant l'original si échec
            arr = []
            for t in chunk:
                one = _run([t])
                arr.append(one[0] if one else t)
        out.extend(str(x) for x in arr)
    return out


def translate_framework_to_french(slug: str, model: str | None = None) -> dict:
    """Traduit en français les libellés d'un référentiel (UPDATE) ET recalcule
    leurs embeddings, pour rester cohérent avec le socle francophone."""
    rows = db.query("select id, label from framework_criterion where framework_slug = %s order by reference", (slug,))
    labels_fr = translate_texts([r["label"] for r in rows], source_hint=slug, model=model)
    vectors = embed_texts(labels_fr)
    updates = [(labels_fr[i], to_pgvector(vectors[i]), rows[i]["id"]) for i in range(len(rows))]
    with db._admin().connection() as conn:
        with conn.transaction():
            conn.cursor().executemany(
                "update framework_criterion set label = %s, embedding = %s::vector where id = %s", updates)
    return {"slug": slug, "translated": len(updates)}


def translate_evidence_to_french(slug: str, model: str | None = None) -> dict:
    """Traduit en français le texte des moyens de vérification (criterion_evidence)
    d'un référentiel."""
    rows = db.query(
        "select distinct ce.detail from criterion_evidence ce"
        " join framework_criterion fc on fc.id = ce.framework_criterion_id"
        " where fc.framework_slug = %s and ce.detail is not null and ce.detail <> ''", (slug,))
    originals = [r["detail"] for r in rows]
    if not originals:
        return {"slug": slug, "translated": 0}
    fr = translate_texts(originals, source_hint=f"moyens de vérification {slug}", model=model)
    mapping = list(zip(fr, originals))  # (nouveau, ancien)
    with db._admin().connection() as conn:
        with conn.transaction():
            conn.cursor().executemany("update criterion_evidence set detail = %s where detail = %s", mapping)
    return {"slug": slug, "translated": len(originals)}


def remap_framework_llm(slug: str, workers: int = 6, model: str | None = None) -> dict:
    """Révise les rattachements d'un référentiel déjà en base via le LLM, en UPDATE
    (préserve les embeddings des critères). Renvoie des statistiques avant/après."""
    from concurrent.futures import ThreadPoolExecutor

    rows = db.query(
        "select id::text as id, label, embedding::text as emb,"
        " common_criterion_id::text as old_cc, degree as old_deg"
        " from framework_criterion where framework_slug = %s and embedding is not null order by reference",
        (slug,),
    )
    # 1. shortlists (lectures DB séquentielles, rapides)
    tasks = [(r, db.match_common(r["emb"], k=6), db.nearest_fc(r["emb"], k=4)) for r in rows]

    # 2. choix LLM en parallèle (sans DB dans les threads)
    def _choose(t):
        r, cands, precs = t
        if not cands:
            return r, None
        try:
            return r, llm_choose(r["label"], cands, precs, model)
        except Exception:
            return r, {"common_code": cands[0]["code"], "degree": r["old_deg"], "confidence": 0.0}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_choose, tasks))

    # 3. application en transaction
    cc = {row["code"]: (row["id"], row["theme_slug"])
          for row in db.query("select code, id, theme_slug from common_criterion")}
    updates, reassigned, redegreed = [], 0, 0
    for r, choice in results:
        if not choice or choice["common_code"] not in cc:
            continue
        cid, theme = cc[choice["common_code"]]
        if str(cid) != str(r["old_cc"]):  # old_cc vient de ::text → comparer en texte
            reassigned += 1
        if choice["degree"] != r["old_deg"]:
            redegreed += 1
        updates.append((cid, choice["degree"], theme, r["id"]))
    with db._admin().connection() as conn:
        with conn.transaction():
            conn.cursor().executemany(
                "update framework_criterion set common_criterion_id = %s, degree = %s, theme_slug = %s where id = %s",
                updates,
            )
    return {"slug": slug, "total": len(rows), "updated": len(updates),
            "reassigned_common": reassigned, "changed_degree": redegreed}


def apply_framework(framework: dict, proposals: list[dict], replace: bool = False) -> dict:
    """Insère le référentiel validé (framework + critères + rattachements + embeddings)
    dans une transaction. Lève ValueError si validation échoue ou slug déjà présent."""
    errors = validate(framework, proposals)
    if errors:
        raise ValueError("; ".join(errors[:8]))

    slug = framework["slug"]
    labels = [p["criterion"] for p in proposals]
    vectors = embed_texts(labels)

    with db._admin().connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            cc = {}  # code → (id, theme_slug) des critères communs connus
            for row in cur.execute("select code, id, theme_slug from common_criterion").fetchall():
                cc[row["code"]] = (row["id"], row["theme_slug"])

            exists = cur.execute("select 1 as ok from framework where slug = %s", (slug,)).fetchone()
            if exists and not replace:
                raise ValueError(f"le référentiel '{slug}' existe déjà (utiliser replace)")
            if exists:
                cur.execute("delete from framework_criterion where framework_slug = %s", (slug,))
                cur.execute("delete from framework where slug = %s", (slug,))

            cur.execute(
                "insert into framework (slug, title, publisher, version, coverage, status)"
                " values (%s, %s, %s, %s, %s, %s)",
                (slug, framework["title"], framework.get("publisher"),
                 framework.get("version"), framework.get("coverage"), framework.get("status", "actif")),
            )
            rows = []
            for p, vec in zip(proposals, vectors):
                sug = p["suggested"]
                cc_id, theme_slug = cc[sug["common_code"]]
                rows.append((slug, p.get("reference"), p["criterion"], theme_slug,
                             p.get("level"), sug["degree"], cc_id, to_pgvector(vec)))
            cur.executemany(
                "insert into framework_criterion"
                " (framework_slug, reference, label, theme_slug, level, degree, common_criterion_id, embedding)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                rows,
            )
    return {"slug": slug, "inserted": len(proposals)}
