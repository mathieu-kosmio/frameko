"""Enrichir criterion_evidence : déduire, pour chaque critère de référentiel
sans type de preuve rattaché, le(s) type(s) de preuve attendu(s) parmi le
catalogue canonique evidence_type — via le LLM (classification).

Contexte : criterion_evidence n'est aujourd'hui rempli que pour FlorEcuador.
Ce script complète les autres référentiels pour que la vue « types de documents
→ référentiels → exigences » et l'évaluation par documents soient exploitables.

Réutilise le client OpenAI et le pool admin (mcp_server.db), comme ingest.py.

Exemples :
    # Aperçu sans écriture sur un petit référentiel
    python scripts/infer_evidence.py --framework charte-qualite-fleurs --dry-run
    # Écriture pour un référentiel
    python scripts/infer_evidence.py --framework planetproof
    # Tous les référentiels manquants
    python scripts/infer_evidence.py --all
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTO))

from mcp_server import db  # noqa: E402

BATCH = 15


def evidence_catalog() -> dict:
    """slug -> {id, label_fr} du catalogue des types de preuve."""
    rows = db.query("select id::text as id, slug, label_fr from evidence_type order by slug")
    return {r["slug"]: r for r in rows}


def missing_criteria(framework: str | None) -> list[dict]:
    """Critères de référentiel sans aucun type de preuve rattaché."""
    sql = (
        "select fc.id::text as id, fc.framework_slug, fc.reference, fc.label"
        " from framework_criterion fc"
        " where not exists (select 1 from criterion_evidence ce"
        "                   where ce.framework_criterion_id = fc.id)"
    )
    params: tuple = ()
    if framework:
        sql += " and fc.framework_slug = %s"
        params = (framework,)
    sql += " order by fc.framework_slug, fc.reference"
    return db.query(sql, params)


def classify_batch(items: list[dict], catalog: dict, model: str) -> dict:
    """Renvoie {index -> [slugs]} pour un lot d'exigences, via le LLM."""
    from openai import OpenAI

    client = OpenAI()
    cat_lines = "\n".join(f"- {slug} : {v['label_fr']}" for slug, v in catalog.items())
    reqs = [{"i": i, "exigence": it["label"]} for i, it in enumerate(items)]
    prompt = (
        "Tu rattaches des exigences de certification au(x) TYPE(S) de preuve attendu(s) "
        "(moyen de vérification). Choisis 1 à 3 types PARMI cette liste fermée (utilise les "
        "slugs exacts ; 'autre' si rien ne convient) :\n" + cat_lines + "\n\n"
        "Pour chaque exigence ci-dessous, donne les slugs les plus pertinents. Réponds en JSON "
        "STRICT : {\"a\": [{\"i\": <index>, \"types\": [\"slug\", ...]}, ...]} avec une entrée par "
        "exigence.\n\n" + json.dumps(reqs, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0)
    data = json.loads(resp.choices[0].message.content)
    out: dict = {}
    for entry in data.get("a", []):
        i = entry.get("i")
        types = [s for s in (entry.get("types") or []) if s in catalog]
        if isinstance(i, int) and 0 <= i < len(items):
            out[i] = types or ["autre"]
    # repli : tout index manquant → 'autre'
    for i in range(len(items)):
        out.setdefault(i, ["autre"])
    return out


def insert_links(crit_id: str, slugs: list[str], catalog: dict) -> int:
    rows = [(crit_id, catalog[s]["id"]) for s in dict.fromkeys(slugs) if s in catalog]
    if not rows:
        return 0
    with db._admin().connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into criterion_evidence (framework_criterion_id, evidence_type_id)"
            " values (%s, %s) on conflict do nothing",
            rows,
        )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework", help="slug d'un référentiel (sinon tous les manquants)")
    ap.add_argument("--all", action="store_true", help="traiter tous les référentiels manquants")
    ap.add_argument("--dry-run", action="store_true", help="aperçu sans écriture")
    ap.add_argument("--limit", type=int, default=0, help="borne le nombre d'exigences (test/coût)")
    args = ap.parse_args()
    if not args.framework and not args.all:
        ap.error("préciser --framework <slug> ou --all")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    catalog = evidence_catalog()
    items = missing_criteria(args.framework)
    if args.limit:
        items = items[: args.limit]
    print(f"[infer_evidence] {len(items)} exigence(s) sans preuve "
          f"({args.framework or 'tous'}) · modèle={model} · dry_run={args.dry_run}", flush=True)

    written = 0
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        assigns = classify_batch(batch, catalog, model)
        for i, it in enumerate(batch):
            slugs = assigns.get(i, ["autre"])
            if args.dry_run:
                print(f"  {it['framework_slug']:22} {it['reference'] or '—':10} "
                      f"{','.join(slugs):24} | {it['label'][:70]}", flush=True)
            else:
                written += insert_links(it["id"], slugs, catalog)
        print(f"[infer_evidence] lot {start//BATCH + 1} : {start+len(batch)}/{len(items)}", flush=True)

    print(f"[infer_evidence] terminé. liens insérés : {written}"
          f"{' (dry-run, aucune écriture)' if args.dry_run else ''}", flush=True)


if __name__ == "__main__":
    main()
