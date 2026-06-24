"""
Tâche 3 — Chargement de l'ontologie dans Postgres.

1. Lit le socle TTL (rdflib) : domaines, catégories, thèmes, critères communs.
2. Lit export_referentiels.csv : 9 référentiels.
3. Lit export_tous_criteres.csv : 876 critères, rattachés à leur critère commun
   par le libellé français exact (skos:prefLabel), thème déduit du critère commun.

Usage :
    cd proto
    python scripts/load_data.py
"""

import csv
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, SKOS

PROTO = Path(__file__).resolve().parent.parent
ONTOLOGIE = PROTO.parent / "ONTOLOGIE"
load_dotenv(PROTO / ".env")

RC = Namespace("https://ontology.kosm.io/socle-commun#")
STD = Namespace("https://ontology.kosm.io/standards/core#")

TTL = ONTOLOGIE / "socle-generique" / "socle-commun-generique.ttl"
CSV_REFERENTIELS = ONTOLOGIE / "export_referentiels.csv"
CSV_CRITERES = ONTOLOGIE / "export_tous_criteres.csv"

# Correspondance des noms de référentiels (les deux CSV divergent) → slug canonique
# slug : (nom court dans export_tous_criteres, nom long dans export_referentiels)
FRAMEWORKS = {
    "florverde": ("Florverde (FSF)", "Florverde Sustainable Flowers (FSF)"),
    "florecuador": ("FlorEcuador", "FlorEcuador Certified"),
    "rainforest-alliance": ("Rainforest Alliance", "Rainforest Alliance, Sustainable Agriculture Standard"),
    "fairtrade": ("Fairtrade", "Fairtrade, Flowers and Plants Standard"),
    "planetproof": ("PlanetProof", "PlanetProof (On the way to PlanetProof - Produits végétaux)"),
    "vivaifiori": ("VivaiFiori", "VivaiFiori"),
    "plante-bleue": ("Plante Bleue", "Plante Bleue"),
    "mps-abc": ("MPS-ABC", "MPS-ABC"),
    "charte-qualite-fleurs": ("Charte Qualité Fleurs", "Charte Qualité Fleurs"),
}
SLUG_BY_SHORT = {short: slug for slug, (short, _long) in FRAMEWORKS.items()}
SLUG_BY_LONG = {long: slug for slug, (_short, long) in FRAMEWORKS.items()}


def slug_of(uri) -> str:
    return str(uri).split("#")[-1]


def pref_label(g: Graph, subj, lang: str) -> str | None:
    for obj in g.objects(subj, SKOS.prefLabel):
        if getattr(obj, "language", None) == lang:
            return str(obj)
    return None


def load_socle(g: Graph, conn: psycopg.Connection) -> None:
    domains, categories, themes, criteria = [], [], [], []

    for subj in g.subjects(RDF.type, STD.Domain):
        domains.append((slug_of(subj), pref_label(g, subj, "fr"), pref_label(g, subj, "en")))

    for subj in g.subjects(RDF.type, STD.Category):
        domain_slug = next((slug_of(o) for o in g.objects(subj, STD.hasDomain)), None)
        categories.append(
            (slug_of(subj), pref_label(g, subj, "fr"), pref_label(g, subj, "en"), domain_slug)
        )

    for subj in g.subjects(RDF.type, STD.Theme):
        category_slug = next((slug_of(o) for o in g.objects(subj, SKOS.broader)), None)
        themes.append(
            (slug_of(subj), pref_label(g, subj, "fr"), pref_label(g, subj, "en"), category_slug)
        )

    for subj in g.subjects(RDF.type, STD.CommonCriterion):
        theme_slug = next((slug_of(o) for o in g.objects(subj, SKOS.broader)), None)
        criteria.append((slug_of(subj), pref_label(g, subj, "fr"), theme_slug))

    with conn.cursor() as cur:
        cur.executemany(
            "insert into domain (slug, label_fr, label_en) values (%s, %s, %s)", domains
        )
        cur.executemany(
            "insert into category (slug, label_fr, label_en, domain_slug) values (%s, %s, %s, %s)",
            categories,
        )
        cur.executemany(
            "insert into theme (slug, label_fr, label_en, category_slug) values (%s, %s, %s, %s)",
            themes,
        )
        cur.executemany(
            "insert into common_criterion (code, label_fr, theme_slug) values (%s, %s, %s)",
            criteria,
        )
    print(f"  domaines={len(domains)} catégories={len(categories)} "
          f"thèmes={len(themes)} critères communs={len(criteria)}")


def load_frameworks(conn: psycopg.Connection) -> None:
    rows = []
    with open(CSV_REFERENTIELS, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            long_name = r["Référentiel"].strip()
            slug = SLUG_BY_LONG.get(long_name)
            if not slug:
                raise ValueError(f"Référentiel inconnu dans export_referentiels.csv : {long_name!r}")
            rows.append((
                slug, long_name, r.get("Éditeur") or None,
                r.get("Version") or None, r.get("Couverture") or None,
                (r.get("Statut") or "actif").strip(),
            ))
    with conn.cursor() as cur:
        cur.executemany(
            "insert into framework (slug, title, publisher, version, coverage, status)"
            " values (%s, %s, %s, %s, %s, %s)",
            rows,
        )
    print(f"  référentiels={len(rows)}")


def load_criteria(conn: psycopg.Connection) -> None:
    # libellé fr du critère commun → (id, theme_slug)
    with conn.cursor() as cur:
        cur.execute("select id, label_fr, theme_slug from common_criterion")
        cc_by_label = {label.strip(): (cid, theme) for cid, label, theme in cur.fetchall()}

    rows, missing = [], []
    with open(CSV_CRITERES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            short = r["Référentiel"].strip()
            slug = SLUG_BY_SHORT.get(short)
            if not slug:
                raise ValueError(f"Référentiel inconnu dans export_tous_criteres.csv : {short!r}")
            cc_label = (r["Critère commun"] or "").strip()
            cc = cc_by_label.get(cc_label)
            if cc is None:
                missing.append(cc_label)
                continue
            cc_id, theme_slug = cc
            rows.append((
                slug, (r.get("Référence") or "").strip() or None,
                r["Critère"].strip(), theme_slug,
                (r.get("Niveau") or "").strip() or None,
                (r.get("Degré") or "").strip(), cc_id,
            ))

    if missing:
        sample = sorted(set(missing))[:5]
        raise ValueError(
            f"{len(missing)} critères sans critère commun rattaché. Exemples : {sample}"
        )

    with conn.cursor() as cur:
        cur.executemany(
            "insert into framework_criterion"
            " (framework_slug, reference, label, theme_slug, level, degree, common_criterion_id)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    print(f"  critères de référentiel={len(rows)}")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERREUR : DATABASE_URL absent de .env", file=sys.stderr)
        return 1

    print(f"Lecture du socle : {TTL.name}")
    g = Graph()
    g.parse(str(TTL), format="turtle")

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate domain, category, theme, common_criterion, framework,"
                " framework_criterion, assessment, assessment_answer"
                " restart identity cascade"
            )
        print("Chargement socle…")
        load_socle(g, conn)
        print("Chargement référentiels…")
        load_frameworks(conn)
        print("Chargement critères…")
        load_criteria(conn)
        conn.commit()

    print("✓ Chargement terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
