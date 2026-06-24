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
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")

_admin_pool: ConnectionPool | None = None
_app_pool: ConnectionPool | None = None


# ── Résolution de la chaîne de connexion ────────────────────────────────────
# Piège connu (hébergement) : l'endpoint Supabase *direct* (db.<ref>.supabase.co)
# et le *transaction pooler* (port 6543) sont en IPv6 par défaut → injoignables
# depuis un hôte IPv4-only (« Network is unreachable »). Sur IPv4, utiliser le
# *Session pooler* (aws-<n>-<region>.pooler.supabase.com:5432) et le passer
# directement dans DATABASE_URL / APP_DATABASE_URL, ou via les variables _POOLER
# avec USE_POOLER activé.

def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _use_pooler() -> bool:
    return _truthy(os.environ.get("USE_POOLER"))


def _resolve_dsn(direct_var: str, pooler_var: str, *, required: bool = True) -> str:
    """Préfère l'URL du pooler quand le pooling est activé et qu'une URL pooler
    est fournie ; sinon l'URL directe. Tolérant sur la valeur de USE_POOLER."""
    if _use_pooler() and os.environ.get(pooler_var):
        return os.environ[pooler_var]
    dsn = os.environ.get(direct_var)
    if not dsn and required:
        raise RuntimeError(f"{direct_var} absent de l'environnement (.env ou variables du conteneur)")
    return dsn or ""


def _host_hint(dsn: str) -> str:
    """host:port/dbname sans identifiants — pour un log de démarrage lisible."""
    try:
        u = urlsplit(dsn)
        return f"{u.hostname}:{u.port or 5432}{u.path or ''}"
    except Exception:
        return "?"


def _open_pool(label: str, dsn: str, *, autocommit: bool, min_size: int) -> ConnectionPool:
    """Ouvre un pool en journalisant l'hôte (sans secret) et en transformant
    l'erreur réseau IPv6/pooler en message actionnable."""
    print(f"[frameko/db] pool '{label}' → {_host_hint(dsn)} (pooler={'on' if _use_pooler() else 'off'})",
          file=sys.stderr, flush=True)
    pool = ConnectionPool(dsn, min_size=min_size, max_size=8, open=False,
                          kwargs={"row_factory": dict_row, "autocommit": autocommit})
    try:
        pool.open(wait=True, timeout=15)
    except Exception as exc:
        msg = str(exc)
        if "unreachable" in msg.lower() or "could not translate" in msg.lower():
            raise RuntimeError(
                f"Connexion base impossible pour le pool '{label}' ({_host_hint(dsn)}). "
                "Sur un hôte IPv4-only (VPS, conteneur), l'endpoint direct et le transaction "
                "pooler Supabase sont en IPv6 : utiliser le Session pooler "
                "(aws-<n>-<region>.pooler.supabase.com:5432). Détail : " + msg
            ) from exc
        raise
    return pool


def _admin() -> ConnectionPool:
    global _admin_pool
    if _admin_pool is None:
        _admin_pool = _open_pool("admin", _resolve_dsn("DATABASE_URL", "DATABASE_POOLER_URL"),
                                 autocommit=True, min_size=1)
    return _admin_pool


def _app() -> ConnectionPool:
    global _app_pool
    if _app_pool is None:
        # autocommit=False → transactions (RLS via SET LOCAL). Le pool « app »
        # respecte aussi le pooler (APP_DATABASE_POOLER_URL) pour rester joignable
        # en IPv4, exactement comme le pool admin.
        app_url = _resolve_dsn("APP_DATABASE_URL", "APP_DATABASE_POOLER_URL", required=False)
        if not app_url:
            raise RuntimeError("APP_DATABASE_URL absent — exécuter scripts/setup_app_role.py")
        _app_pool = _open_pool("app", app_url, autocommit=False, min_size=0)
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


def framework_criteria(slug: str) -> list[dict]:
    """Tous les critères d'un référentiel, avec thème/catégorie et rattachement au
    socle commun — pour la vue « parcourir un référentiel »."""
    return query(
        "select fc.reference, fc.label, fc.level, fc.degree,"
        "       cc.code as common_code, cc.label_fr as common_label,"
        "       t.slug as theme_slug, t.label_fr as theme_label,"
        "       cat.label_fr as category_label"
        " from framework_criterion fc"
        " join common_criterion cc on cc.id = fc.common_criterion_id"
        " left join theme t on t.slug = fc.theme_slug"
        " left join category cat on cat.slug = t.category_slug"
        " where fc.framework_slug = %s"
        " order by cat.label_fr nulls last, t.label_fr nulls last, cc.code, fc.reference",
        (slug,),
    )


def neighbors(slug: str) -> list[dict]:
    """Référentiels partageant des critères communs avec « slug » (voisinage)."""
    return query("select * from framework_neighbors(%s)", (slug,))


def pair_detail(a: str, b: str) -> list[dict]:
    """Comparaison au niveau critère : exigences d'origine des deux référentiels
    pour chaque critère commun partagé (avec degré)."""
    return query("select * from framework_pair_detail(%s, %s)", (a, b))


# ── Couche de reconnaissance / équivalence (FSI) ────────────────────────────

def recognitions(scheme: str) -> list[dict]:
    """Standards reconnus par un schéma (ex. FSI), avec le titre du référentiel
    quand il est présent dans notre base."""
    return query(
        "select r.pillar, r.framework_label, r.framework_slug, r.status, f.title as framework_title"
        " from recognition r left join framework f on f.slug = r.framework_slug"
        " where r.scheme_slug = %s order by r.pillar, r.framework_label",
        (scheme,),
    )


def recognition_scheme(scheme: str) -> dict | None:
    return query_one("select slug, name, description, url from recognition_scheme where slug = %s", (scheme,))


def framework_equivalences(slug: str) -> list[dict]:
    """Référentiels (en base) co-reconnus avec « slug » dans au moins un pilier
    commun — donc équivalents au sens du marché."""
    return query("select * from framework_equivalences(%s)", (slug,))


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
