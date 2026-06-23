"""
Charge l'ontologie RDF existante (floriscore-referentiels.ttl) dans Postgres.

Usage :
    cd proto
    python scripts/seed_ontology.py --ttl ../ONTOLOGIE/floriscore-referentiels.ttl
"""

import argparse
import asyncio
import logging
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from rdflib import Graph, Namespace, RDF, SKOS, URIRef
from rdflib.namespace import RDFS

load_dotenv()

import os

DATABASE_URL = os.environ["DATABASE_URL"]

FLO = Namespace("https://ontology.kosm.io/floriscore/ref#")
CCCEV = Namespace("http://data.europa.eu/m8g/")

logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")


async def seed(ttl_path: Path) -> None:
    logger.info("Chargement du graphe RDF depuis %s …", ttl_path)
    g = Graph()
    g.parse(str(ttl_path), format="turtle")
    logger.info("%d triples chargés", len(g))

    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=False) as conn:
        # Domaine horticole par défaut
        domain_id = await _upsert_domain(conn)

        # Thèmes (skos:Concept de type flo:Theme)
        theme_map = await _seed_themes(conn, g, domain_id)

        # Critères communs
        cc_map = await _seed_common_criteria(conn, g, theme_map)

        # Référentiels
        fw_map = await _seed_frameworks(conn, g, domain_id)

        # Critères de référentiel + mappings
        await _seed_framework_criteria(conn, g, fw_map, cc_map, theme_map)

        await conn.commit()
    logger.info("Seed terminé.")


async def _upsert_domain(conn: psycopg.AsyncConnection) -> str:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO domain (slug, label_fr, label_en)
            VALUES ('horticulture', 'Horticulture', 'Horticulture')
            ON CONFLICT (slug) DO UPDATE SET label_fr = EXCLUDED.label_fr
            RETURNING id
            """
        )
        return (await cur.fetchone())[0]  # type: ignore[index]


async def _seed_themes(
    conn: psycopg.AsyncConnection, g: Graph, domain_id: str
) -> dict[str, str]:
    """Insère catégories (7) et thèmes (13), retourne {iri -> id}."""
    # Catégorie générique unique pour le prototype
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO category (slug, label_fr, domain_id)
            VALUES ('referentiels-horticoles', 'Référentiels horticoles', %s)
            ON CONFLICT (slug) DO UPDATE SET domain_id = EXCLUDED.domain_id
            RETURNING id
            """,
            [domain_id],
        )
        cat_id = (await cur.fetchone())[0]  # type: ignore[index]

    theme_map: dict[str, str] = {}
    for subj in g.subjects(RDF.type, FLO.Theme):
        label_fr = _label(g, subj, "fr") or str(subj).split("#")[-1]
        label_en = _label(g, subj, "en")
        slug = str(subj).split("#")[-1].lower().replace("_", "-")
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO theme (slug, label_fr, label_en, category_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET label_fr = EXCLUDED.label_fr
                RETURNING id
                """,
                [slug, label_fr, label_en, cat_id],
            )
            theme_map[str(subj)] = (await cur.fetchone())[0]  # type: ignore[index]

    logger.info("%d thèmes insérés", len(theme_map))
    return theme_map


async def _seed_common_criteria(
    conn: psycopg.AsyncConnection, g: Graph, theme_map: dict[str, str]
) -> dict[str, str]:
    cc_map: dict[str, str] = {}
    for subj in g.subjects(RDF.type, FLO.CritereCommun):
        code = _notation(g, subj) or str(subj).split("#")[-1]
        label_fr = _label(g, subj, "fr") or code
        label_en = _label(g, subj, "en")
        definition = _definition(g, subj)
        theme_id = None
        for t in g.objects(subj, SKOS.inScheme):
            theme_id = theme_map.get(str(t))
        # hasConcept -> theme
        for t in g.objects(subj, CCCEV.hasConcept):
            theme_id = theme_map.get(str(t)) or theme_id

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO common_criterion
                    (code, label_fr, label_en, definition, theme_id, iri)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET label_fr = EXCLUDED.label_fr
                RETURNING id
                """,
                [code, label_fr, label_en, definition, theme_id, str(subj)],
            )
            cc_map[str(subj)] = (await cur.fetchone())[0]  # type: ignore[index]

    logger.info("%d critères communs insérés", len(cc_map))
    return cc_map


async def _seed_frameworks(
    conn: psycopg.AsyncConnection, g: Graph, domain_id: str
) -> dict[str, str]:
    fw_map: dict[str, str] = {}
    for subj in g.subjects(RDF.type, FLO.Referentiel):
        title = _label(g, subj, "fr") or str(subj).split("#")[-1]
        slug = str(subj).split("#")[-1].lower().replace("_", "-")
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO framework (slug, title, domain_id, iri)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title
                RETURNING id
                """,
                [slug, title, domain_id, str(subj)],
            )
            fw_map[str(subj)] = (await cur.fetchone())[0]  # type: ignore[index]

    logger.info("%d référentiels insérés", len(fw_map))
    return fw_map


async def _seed_framework_criteria(
    conn: psycopg.AsyncConnection,
    g: Graph,
    fw_map: dict[str, str],
    cc_map: dict[str, str],
    theme_map: dict[str, str],
) -> None:
    DEGREE_PROPS = {
        str(FLO.equivautA): "equivautA",
        str(FLO.plusStrictQue): "plusStrictQue",
        str(FLO.plusLargeQue): "plusLargeQue",
        str(FLO.rapprocheDe): "rapprocheDe",
    }

    inserted_fc = 0
    inserted_m = 0

    for subj in g.subjects(RDF.type, FLO.CritereReferentiel):
        label_fr = _label(g, subj, "fr") or str(subj).split("#")[-1]
        reference = _notation(g, subj)

        # Référentiel parent (via cccev:isDerivedFrom ou flo:appartientA)
        framework_id = None
        for parent in g.objects(subj, CCCEV.isDerivedFrom):
            framework_id = fw_map.get(str(parent))
        if not framework_id:
            for parent in g.objects(subj, FLO.appartientA):
                framework_id = fw_map.get(str(parent))
        if not framework_id:
            continue

        theme_id = None
        for t in g.objects(subj, CCCEV.hasConcept):
            theme_id = theme_map.get(str(t))

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO framework_criterion
                    (framework_id, reference, label, theme_id, iri)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (iri) DO UPDATE SET label = EXCLUDED.label
                RETURNING id
                """,
                [framework_id, reference, label_fr, theme_id, str(subj)],
            )
            fc_id = (await cur.fetchone())[0]  # type: ignore[index]
            inserted_fc += 1

        # Mappings vers critères communs
        for prop_iri, degree in DEGREE_PROPS.items():
            for obj in g.objects(subj, URIRef(prop_iri)):
                cc_id = cc_map.get(str(obj))
                if cc_id:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO mapping
                                (framework_criterion_id, common_criterion_id, degree)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (framework_criterion_id, common_criterion_id)
                            DO UPDATE SET degree = EXCLUDED.degree
                            """,
                            [fc_id, cc_id, degree],
                        )
                        inserted_m += 1

    logger.info("%d critères de référentiel insérés, %d mappings", inserted_fc, inserted_m)


def _label(g: Graph, subj: URIRef, lang: str) -> str | None:
    for obj in g.objects(subj, RDFS.label):
        if hasattr(obj, "language") and obj.language == lang:
            return str(obj)
    return None


def _notation(g: Graph, subj: URIRef) -> str | None:
    for obj in g.objects(subj, SKOS.notation):
        return str(obj)
    return None


def _definition(g: Graph, subj: URIRef) -> str | None:
    for obj in g.objects(subj, SKOS.definition):
        return str(obj)
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ontologie Frameko depuis un fichier Turtle")
    parser.add_argument("--ttl", default="../ONTOLOGIE/floriscore-referentiels.ttl")
    args = parser.parse_args()
    asyncio.run(seed(Path(args.ttl)))
