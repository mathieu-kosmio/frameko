"""
Accès base de données pour le serveur MCP.

Connexion via DATABASE_POOLER_URL si défini (recommandé pour le runtime),
sinon DATABASE_URL. Les identifiants sont lus depuis proto/.env.
"""

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")

_CONN: psycopg.Connection | None = None


def _dsn() -> str:
    # Connexion directe par défaut (fiable). Le pooler Supabase n'est utilisé que
    # si USE_POOLER=1 ET sa région est confirmée dans DATABASE_POOLER_URL.
    if os.environ.get("USE_POOLER") == "1" and os.environ.get("DATABASE_POOLER_URL"):
        return os.environ["DATABASE_POOLER_URL"]
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL absent de .env")
    return dsn


def conn() -> psycopg.Connection:
    """Connexion persistante, reconnectée si fermée."""
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = psycopg.connect(_dsn(), autocommit=True, row_factory=dict_row)
    return _CONN


def query(sql: str, params: tuple = ()) -> list[dict]:
    with conn().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


# ── Référentiels (S1) ───────────────────────────────────────────────────────

def list_frameworks() -> list[dict]:
    return query(
        "select slug, title, publisher, version, coverage, status,"
        " (select count(*) from framework_criterion fc where fc.framework_slug = f.slug) as n_criteres"
        " from framework f order by n_criteres desc"
    )


def get_framework(slug: str) -> dict | None:
    fw = query_one("select slug, title, publisher, version, coverage, status from framework where slug = %s", (slug,))
    if not fw:
        return None
    fw["criteres"] = query(
        "select reference, label, level, degree,"
        " (select code from common_criterion cc where cc.id = fc.common_criterion_id) as common_code"
        " from framework_criterion fc where framework_slug = %s order by reference",
        (slug,),
    )
    return fw


# ── Recherche sémantique (S2) ───────────────────────────────────────────────

def match_common(vec_literal: str, k: int = 8) -> list[dict]:
    return query("select * from match_criteria(%s::vector, %s)", (vec_literal, k))


def nearest_fc(vec_literal: str, k: int = 10) -> list[dict]:
    return query("select * from nearest_framework_criteria(%s::vector, %s)", (vec_literal, k))


def coverage(a: str, b: str) -> list[dict]:
    return query("select * from framework_coverage(%s, %s)", (a, b))


# ── Auto-évaluation (S3) ────────────────────────────────────────────────────

def framework_exists(slug: str) -> bool:
    return query_one("select 1 as ok from framework where slug = %s", (slug,)) is not None


def start_assessment(framework_slug: str) -> str:
    row = query_one(
        "insert into assessment (framework_slug) values (%s) returning id", (framework_slug,)
    )
    return str(row["id"])


def common_criterion_by_label(label: str) -> dict | None:
    return query_one(
        "select id, code, label_fr from common_criterion where lower(label_fr) = lower(%s)",
        (label.strip(),),
    )


def upsert_answer(assessment_id: str, common_criterion_id: str, status: str, note: str | None) -> None:
    with conn().cursor() as cur:
        cur.execute(
            "insert into assessment_answer (assessment_id, common_criterion_id, status, note)"
            " values (%s, %s, %s, %s)"
            " on conflict (assessment_id, common_criterion_id)"
            " do update set status = excluded.status, note = excluded.note",
            (assessment_id, common_criterion_id, status, note),
        )


def assessment_result(assessment_id: str) -> dict | None:
    row = query_one("select assessment_result(%s) as r", (assessment_id,))
    return row["r"] if row else None
