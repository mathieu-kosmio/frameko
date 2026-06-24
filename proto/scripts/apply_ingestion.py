"""
Étape « apply » du pipeline d'ingestion — insertion en base d'un référentiel validé.

Lit un proposals.json (produit par ingest_framework.py puis VALIDÉ par un agent ou
un humain : chaque proposition doit porter un `suggested.common_code` existant et un
`suggested.degree` parmi les 4 valeurs). Insère le référentiel, ses critères, leurs
rattachements au socle commun, et calcule les embeddings.

Usage :
    python scripts/apply_ingestion.py --proposals proposals.json \
        [--publisher "…"] [--version "…"] [--coverage "…"] [--replace]

Garde-fous :
- refuse d'écrire si une proposition n'a pas de degré (validation requise) ;
- refuse un common_code inconnu ;
- --replace est requis pour réinsérer un slug déjà présent (sinon erreur).
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

from mcp_server.embeddings import embed_texts, to_pgvector  # noqa: E402
import os  # noqa: E402

DEGREES = {"equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposals", required=True)
    ap.add_argument("--publisher", default=None)
    ap.add_argument("--version", default=None)
    ap.add_argument("--coverage", default=None)
    ap.add_argument("--status", default="actif")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    path = Path(args.proposals)
    if not path.is_absolute():
        path = PROTO / args.proposals
    data = json.loads(path.read_text(encoding="utf-8"))

    fw = data.get("framework") or {}
    slug, title = fw.get("slug"), fw.get("title")
    if not slug or not title:
        print("ERREUR : framework.slug et framework.title requis", file=sys.stderr)
        return 1
    proposals = data.get("proposals") or []
    if not proposals:
        print("ERREUR : aucune proposition", file=sys.stderr)
        return 1

    # ── Validation (avant toute écriture) ───────────────────────────────────
    errors = []
    for i, p in enumerate(proposals, 1):
        sug = p.get("suggested") or {}
        if not sug.get("common_code"):
            errors.append(f"#{i} ({p.get('reference')}): common_code manquant")
        if sug.get("degree") not in DEGREES:
            errors.append(f"#{i} ({p.get('reference')}): degré invalide/absent ({sug.get('degree')!r}) — validation requise")
    if errors:
        print("VALIDATION ÉCHOUÉE — corrige proposals.json avant apply :", file=sys.stderr)
        for e in errors[:15]:
            print("  -", e, file=sys.stderr)
        return 1

    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=False) as conn, conn.cursor() as cur:
        # codes communs connus → (id, theme_slug)
        cur.execute("select code, id, theme_slug from common_criterion")
        cc = {code: (cid, theme) for code, cid, theme in cur.fetchall()}
        unknown = sorted({p["suggested"]["common_code"] for p in proposals if p["suggested"]["common_code"] not in cc})
        if unknown:
            print(f"ERREUR : codes communs inconnus : {unknown}", file=sys.stderr)
            return 1

        cur.execute("select 1 from framework where slug = %s", (slug,))
        exists = cur.fetchone() is not None
        if exists and not args.replace:
            print(f"ERREUR : le référentiel '{slug}' existe déjà. Utilise --replace.", file=sys.stderr)
            return 1
        if exists:
            # pas d'ON DELETE CASCADE sur framework_criterion → supprimer les enfants d'abord
            cur.execute("delete from framework_criterion where framework_slug = %s", (slug,))
            cur.execute("delete from framework where slug = %s", (slug,))

        cur.execute(
            "insert into framework (slug, title, publisher, version, coverage, status)"
            " values (%s, %s, %s, %s, %s, %s)",
            (slug, title, args.publisher, args.version, args.coverage, args.status),
        )

        # embeddings des libellés
        labels = [p["criterion"] for p in proposals]
        vectors = embed_texts(labels)

        rows = []
        for p, vec in zip(proposals, vectors):
            sug = p["suggested"]
            cc_id, theme_slug = cc[sug["common_code"]]
            rows.append((
                slug, p.get("reference"), p["criterion"], theme_slug,
                p.get("level"), sug["degree"], cc_id, to_pgvector(vec),
            ))
        cur.executemany(
            "insert into framework_criterion"
            " (framework_slug, reference, label, theme_slug, level, degree, common_criterion_id, embedding)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
            rows,
        )
        conn.commit()

    print(f"✓ Référentiel '{slug}' inséré : {len(proposals)} critères (avec embeddings et rattachements).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
