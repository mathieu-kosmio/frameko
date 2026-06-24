"""
Accès base de données pour le serveur MCP.

Deux pools de connexions (sûrs en concurrence, pour un service hébergé multi-utilisateurs) :
- pool « admin » (DATABASE_URL) pour les lectures publiques (référentiels, critères) ;
- pool « app » (APP_DATABASE_URL, rôle frameko_app sans BYPASSRLS) pour les
  auto-évaluations, soumises à la RLS via SET LOCAL app.current_org_id.

Les identifiants sont lus depuis proto/.env.
"""

import atexit
import os
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")

_admin_pool: ConnectionPool | None = None
_app_pool: ConnectionPool | None = None


def _dsn() -> str:
    # Connexion directe par défaut (fiable). Le pooler Supabase n'est utilisé que
    # si USE_POOLER=1 ET sa région est confirmée dans DATABASE_POOLER_URL.
    if os.environ.get("USE_POOLER") == "1" and os.environ.get("DATABASE_POOLER_URL"):
        return os.environ["DATABASE_POOLER_URL"]
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL absent de .env")
    return dsn


def _admin() -> ConnectionPool:
    global _admin_pool
    if _admin_pool is None:
        _admin_pool = ConnectionPool(
            _dsn(), min_size=1, max_size=8, open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        _admin_pool.open()
    return _admin_pool


def _app() -> ConnectionPool:
    global _app_pool
    if _app_pool is None:
        app_url = os.environ.get("APP_DATABASE_URL")
        if not app_url:
            raise RuntimeError("APP_DATABASE_URL absent — exécuter scripts/setup_app_role.py")
        _app_pool = ConnectionPool(
            app_url, min_size=0, max_size=8, open=False,
            kwargs={"row_factory": dict_row},  # autocommit=False → transactions (RLS)
        )
        _app_pool.open()
    return _app_pool


@atexit.register
def _close_pools() -> None:
    for p in (_admin_pool, _app_pool):
        if p is not None:
            try:
                p.close()
            except Exception:
                pass


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _admin().connection() as conn, conn.cursor() as cur:
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


def common_criterion_by_label(label: str) -> dict | None:
    return query_one(
        "select id, code, label_fr from common_criterion where lower(label_fr) = lower(%s)",
        (label.strip(),),
    )


# ── Isolation par organisation (RLS) ────────────────────────────────────────
# Les opérations d'auto-évaluation passent par le rôle frameko_app (sans
# BYPASSRLS) via APP_DATABASE_URL, dans une transaction où l'org courante est
# fixée par SET LOCAL app.current_org_id. La RLS garantit le cloisonnement.

@contextmanager
def org_scope(org_id: str):
    # Connexion du pool app (rôle frameko_app). La transaction est gérée par le
    # pool (commit en sortie normale, rollback sur exception) ; SET LOCAL scope
    # l'org à cette transaction → pas de fuite entre requêtes.
    with _app().connection() as c:
        c.execute("select set_config('app.current_org_id', %s, true)", (str(org_id),))
        yield c


def start_assessment(org_id: str, framework_slug: str) -> str:
    with org_scope(org_id) as c:
        row = c.execute(
            "insert into assessment (org_id, framework_slug) values (%s, %s) returning id",
            (org_id, framework_slug),
        ).fetchone()
    return str(row["id"])


def upsert_answer(org_id: str, assessment_id: str, common_criterion_id: str,
                  status: str, note: str | None) -> bool:
    """Retourne False si l'évaluation n'appartient pas à l'org (RLS : 0 ligne touchée)."""
    with org_scope(org_id) as c:
        cur = c.execute(
            "insert into assessment_answer (assessment_id, common_criterion_id, status, note)"
            " select %s, %s, %s, %s where exists (select 1 from assessment where id = %s)"
            " on conflict (assessment_id, common_criterion_id)"
            " do update set status = excluded.status, note = excluded.note",
            (assessment_id, common_criterion_id, status, note, assessment_id),
        )
        return cur.rowcount > 0


def assessment_result(org_id: str, assessment_id: str) -> dict | None:
    with org_scope(org_id) as c:
        row = c.execute("select assessment_result(%s) as r", (assessment_id,)).fetchone()
    # un assessment d'une autre org est invisible (RLS) → framework_slug null
    if row and row["r"] and row["r"].get("framework_slug"):
        return row["r"]
    return None
