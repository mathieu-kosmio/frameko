"""
Charge les liens critère ↔ type de preuve depuis un CSV (Code, Preuve, TypesPreuve).

Relie chaque ligne au critère existant du référentiel via sa référence (Code).
Les types de preuves (TypesPreuve, slugs séparés par « | ») doivent exister dans
la table evidence_type (cf. db/06_evidence.sql).

Usage :
    python scripts/load_evidence.py --csv sources/florecuador-evidence.csv --slug florecuador [--replace]
"""

import argparse
import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

from mcp_server import db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--replace", action="store_true", help="repartir des liens existants de ce référentiel")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.is_absolute():
        path = PROTO / args.csv

    # Catalogue des types + critères du référentiel (référence → id)
    types = {r["slug"]: r["id"] for r in db.query("select slug, id from evidence_type")}
    crit = {r["reference"]: r["id"] for r in db.query(
        "select reference, id from framework_criterion where framework_slug = %s", (args.slug,))}

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    links, miss_code, miss_type = [], [], set()
    for r in rows:
        code = (r.get("Code") or "").strip()
        if code not in crit:
            miss_code.append(code)
            continue
        detail = (r.get("Preuve") or "").strip() or None
        for slug in (r.get("TypesPreuve") or "").split("|"):
            slug = slug.strip()
            if not slug:
                continue
            if slug not in types:
                miss_type.add(slug)
                continue
            links.append((crit[code], types[slug], detail))

    if miss_type:
        print(f"ERREUR : types de preuves inconnus : {sorted(miss_type)}", file=sys.stderr)
        return 1

    with db._admin().connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            if args.replace:
                cur.execute(
                    "delete from criterion_evidence where framework_criterion_id in"
                    " (select id from framework_criterion where framework_slug = %s)", (args.slug,))
            cur.executemany(
                "insert into criterion_evidence (framework_criterion_id, evidence_type_id, detail)"
                " values (%s, %s, %s) on conflict (framework_criterion_id, evidence_type_id)"
                " do update set detail = excluded.detail",
                links)

    print(f"✓ {len(links)} liens critère↔preuve insérés pour '{args.slug}'"
          f" ({len(rows)} lignes CSV, {len(set(c for c,_,_ in links))} critères couverts).")
    if miss_code:
        print(f"  ⚠ {len(miss_code)} codes du CSV sans critère correspondant en base : {miss_code[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
