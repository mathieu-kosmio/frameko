"""
Ingestion assistée d'un nouveau référentiel (étape « rattachement » du pipeline).

Pour chaque exigence d'un nouveau référentiel, propose son rattachement au socle
commun. Deux modes :

  • défaut (MCP-first) : produit, par exigence, la liste des critères communs
    candidats (par similarité) + des précédents qualifiés. Le rattachement final
    est décidé par l'agent (Claude via l'outil MCP propose_mapping) ou un humain.

  • --llm (stack OpenAI) : ingestion batch autonome. Le modèle choisit le critère
    commun et le degré, avec un score de confiance et une justification.

Sortie : un fichier proposals.json (DRY-RUN, aucune écriture en base). La validation
puis l'insertion restent une étape séparée.

Usage :
    python scripts/ingest_framework.py --csv nouveau.csv --slug mon-label --title "Mon Label" \
        [--llm] [--limit N] [--out proposals.json]

Le CSV doit contenir au moins une colonne « Critère » (et idéalement « Référence »).
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

from mcp_server import db  # noqa: E402
from mcp_server.embeddings import embed_one, to_pgvector  # noqa: E402

DEGREES = ["equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"]


def read_criteria(path: Path, limit: int | None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # tolérance sur les noms de colonnes
        cols = {c.lower().strip(): c for c in reader.fieldnames or []}
        col_crit = cols.get("critère") or cols.get("critere") or cols.get("label")
        col_ref = cols.get("référence") or cols.get("reference") or cols.get("ref")
        if not col_crit:
            raise ValueError("Colonne « Critère » introuvable dans le CSV.")
        for r in reader:
            label = (r[col_crit] or "").strip()
            if not label:
                continue
            rows.append({"reference": (r.get(col_ref) or "").strip() or None, "criterion": label})
            if limit and len(rows) >= limit:
                break
    return rows


def shortlist(text: str) -> tuple[list[dict], list[dict]]:
    vec = to_pgvector(embed_one(text))
    candidates = db.match_common(vec, k=6)
    precedents = db.nearest_fc(vec, k=4)
    return candidates, precedents


def llm_choose(model: str, criterion: str, candidates: list[dict], precedents: list[dict]) -> dict:
    """Demande au modèle OpenAI de choisir le critère commun et le degré (JSON)."""
    from openai import OpenAI

    client = OpenAI()  # lit OPENAI_API_KEY depuis l'environnement
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
        "Réponds en JSON strict : "
        '{"common_code": "...", "degree": "...", "confidence": 0.0-1.0, "justification": "..."}'
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    out = json.loads(resp.choices[0].message.content)
    # garde-fous : le code doit être un candidat, le degré valide
    valid_codes = {c["code"] for c in candidates}
    if out.get("common_code") not in valid_codes:
        out["common_code"] = candidates[0]["code"]
        out["_note"] = "code hors candidats → repli sur le plus proche"
    if out.get("degree") not in DEGREES:
        out["degree"] = "rapprocheDe"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--llm", action="store_true", help="ingestion autonome via OpenAI")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default="proposals.json")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = PROTO / args.csv
    criteria = read_criteria(csv_path, args.limit)
    print(f"{len(criteria)} exigences à rattacher (référentiel {args.slug}).")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if args.llm and not os.environ.get("OPENAI_API_KEY"):
        print("ERREUR : --llm demandé mais OPENAI_API_KEY absent de .env", file=sys.stderr)
        return 1

    proposals = []
    for i, item in enumerate(criteria, 1):
        candidates, precedents = shortlist(item["criterion"])
        prop = {
            "reference": item["reference"],
            "criterion": item["criterion"],
            "candidates": [
                {"common_code": c["code"], "label": c["label_fr"], "similarity": round(c["similarity"], 3)}
                for c in candidates
            ],
        }
        if args.llm:
            prop["suggested"] = llm_choose(model, item["criterion"], candidates, precedents)
            s = prop["suggested"]
            print(f"  [{i}/{len(criteria)}] → {s['common_code']} / {s['degree']} (conf {s.get('confidence')})")
        else:
            top = candidates[0]
            prop["suggested"] = {
                "common_code": top["code"],
                "degree": None,  # à décider par l'agent
                "confidence": round(top["similarity"], 3),
            }
            print(f"  [{i}/{len(criteria)}] candidat principal → {top['code']} (sim {round(top['similarity'],3)})")
        proposals.append(prop)

    out = {
        "framework": {"slug": args.slug, "title": args.title},
        "mode": "openai" if args.llm else "mcp-first",
        "model": model if args.llm else None,
        "count": len(proposals),
        "proposals": proposals,
    }
    out_path = PROTO / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Propositions écrites (DRY-RUN, aucune écriture en base) : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
