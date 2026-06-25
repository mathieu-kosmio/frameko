"""
Frameko — UI web légère (Starlette).

Interface de démonstration locale des trois services : recherche sémantique,
comparaison de référentiels, auto-évaluation de conformité. Réutilise la même
couche d'accès (mcp_server.db) et le même modèle d'embedding que le serveur MCP.

Lancement :
    cd proto
    .venv/bin/python web/app.py            # http://127.0.0.1:8080
"""

import os
import secrets
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

PROTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTO))

from mcp_server import auth, db, ingest  # noqa: E402
from mcp_server.embeddings import embed_one, to_pgvector  # noqa: E402

import tempfile  # noqa: E402

WEB = Path(__file__).resolve().parent
VALID_STATUS = {"conforme", "partiel", "non_conforme", "non_applicable"}


# Le HTML embarque tout le JS de la console : on interdit la mise en cache pour
# qu'un déploiement soit pris en compte immédiatement (sinon le navigateur sert
# une ancienne version et les nouvelles fonctionnalités semblent ne pas marcher).
_NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


async def landing(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "landing.html").read_text(encoding="utf-8"), headers=_NOCACHE)


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"), headers=_NOCACHE)


async def docs(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "docs.html").read_text(encoding="utf-8"), headers=_NOCACHE)


async def api_frameworks(request: Request) -> JSONResponse:
    return JSONResponse(db.list_frameworks())


async def api_search(request: Request) -> JSONResponse:
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query vide"}, status_code=400)
    framework = body.get("framework") or None
    vec = to_pgvector(embed_one(query))
    common = db.match_common(vec, k=8)
    fc = db.nearest_fc(vec, k=40)
    if framework:
        fc = [r for r in fc if r["framework_slug"] == framework]
    return JSONResponse({"common_criteria": common, "framework_criteria": fc[:12]})


async def api_compare(request: Request) -> JSONResponse:
    body = await request.json()
    a, b = body.get("a"), body.get("b")
    if not db.framework_exists(a) or not db.framework_exists(b):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=400)
    rows = db.coverage(a, b)
    shared = [r for r in rows if r["count_a"] > 0 and r["count_b"] > 0]
    only_a = [r for r in rows if r["count_a"] > 0 and r["count_b"] == 0]
    only_b = [r for r in rows if r["count_b"] > 0 and r["count_a"] == 0]
    return JSONResponse({
        "summary": {"communs_partages": len(shared), "seulement_a": len(only_a), "seulement_b": len(only_b)},
        "detail": rows,
    })


async def api_framework_detail(request: Request) -> JSONResponse:
    """Détail d'un référentiel : métadonnées + tous ses critères groupés par thème."""
    slug = request.path_params["slug"]
    fw = next((f for f in db.list_frameworks() if f["slug"] == slug), None)
    if not fw:
        return JSONResponse({"error": "référentiel inconnu"}, status_code=404)
    return JSONResponse({"framework": fw, "criteria": db.framework_criteria(slug)})


async def api_neighbors(request: Request) -> JSONResponse:
    """Voisinage d'un référentiel : ceux qui partagent des critères communs."""
    slug = request.path_params["slug"]
    if not db.framework_exists(slug):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=404)
    return JSONResponse({"focal": slug, "neighbors": db.neighbors(slug)})


async def api_pair(request: Request) -> JSONResponse:
    """Comparaison détaillée (au niveau critère) de deux référentiels."""
    a = request.query_params.get("a")
    b = request.query_params.get("b")
    if not db.framework_exists(a) or not db.framework_exists(b):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=400)
    rows = db.coverage(a, b)
    shared = [r for r in rows if r["count_a"] > 0 and r["count_b"] > 0]
    only_a = [r for r in rows if r["count_a"] > 0 and r["count_b"] == 0]
    only_b = [r for r in rows if r["count_b"] > 0 and r["count_a"] == 0]
    return JSONResponse({
        "summary": {"communs_partages": len(shared),
                    "seulement_a": len(only_a), "seulement_b": len(only_b)},
        "detail": db.pair_detail(a, b),
        "only_a": only_a,
        "only_b": only_b,
    })


async def api_recognition(request: Request) -> JSONResponse:
    """Couche d'équivalence : panier d'un schéma de reconnaissance (ex. FSI),
    groupé par pilier, avec le nombre de référentiels présents dans notre base."""
    scheme = request.path_params["scheme"]
    info = db.recognition_scheme(scheme)
    if not info:
        return JSONResponse({"error": "schéma inconnu"}, status_code=404)
    rows = db.recognitions(scheme)
    pillars: dict[str, list] = {}
    for r in rows:
        pillars.setdefault(r["pillar"], []).append(r)
    by_pillar = [
        {"pillar": p, "standards": items,
         "in_base": sum(1 for i in items if i["framework_slug"])}
        for p, items in pillars.items()
    ]
    return JSONResponse({"scheme": info, "pillars": by_pillar,
                         "total": len(rows),
                         "in_base": sum(1 for r in rows if r["framework_slug"])})


async def api_equivalences(request: Request) -> JSONResponse:
    """Référentiels équivalents (co-reconnus FSI) à un référentiel donné."""
    slug = request.path_params["slug"]
    if not db.framework_exists(slug):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=404)
    return JSONResponse({"focal": slug, "equivalences": db.framework_equivalences(slug)})


async def api_doc_types(request: Request) -> JSONResponse:
    """Catalogue des types de documents + nb de référentiels/exigences liés."""
    return JSONResponse(db.document_types())


async def api_doc_type_frameworks(request: Request) -> JSONResponse:
    """Référentiels qui attendent un type de document donné."""
    return JSONResponse(db.doc_type_frameworks(request.path_params["slug"]))


async def api_doc_type_criteria(request: Request) -> JSONResponse:
    """Exigences d'un référentiel rattachées à un type de document."""
    return JSONResponse(db.doc_type_framework_criteria(
        request.path_params["slug"], request.path_params["fw"]))


async def api_common_criterion(request: Request) -> JSONResponse:
    """Détail d'un critère commun : toutes les exigences des référentiels liées."""
    code = request.path_params["code"]
    detail = db.common_criterion_detail(code)
    if not detail:
        return JSONResponse({"error": "critère commun inconnu"}, status_code=404)
    return JSONResponse(detail)


async def api_common_criteria(request: Request) -> JSONResponse:
    """Critères communs couverts par un référentiel (pour l'auto-évaluation)."""
    slug = request.query_params.get("framework")
    rows = db.query(
        "select distinct cc.id::text as id, cc.code, cc.label_fr, cc.theme_slug"
        " from framework_criterion fc join common_criterion cc on cc.id = fc.common_criterion_id"
        " where fc.framework_slug = %s order by cc.code",
        (slug,),
    )
    return JSONResponse(rows)


# ── Ingestion / Digitalisation (wizard) ──────────────────────────────────────

INGEST_LIMIT = 60  # borne de coût du proto (rattachement = 2 requêtes vectorielles / exigence)


async def api_ingest_extract(request: Request) -> JSONResponse:
    """Étape 1 : une source uploadée → liste d'exigences (lecture seule)."""
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "fichier manquant"}, status_code=400)
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv", ".tsv", ".pdf"}:
        return JSONResponse({"error": f"format non supporté : {suffix}"}, status_code=400)
    data = await upload.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            criteria = ingest.extract_from_path(Path(tmp.name))
        except Exception as exc:  # extraction tolérante : on remonte l'erreur lisible
            return JSONResponse({"error": f"extraction impossible : {exc}"}, status_code=400)
    return JSONResponse({"filename": upload.filename, "count": len(criteria), "criteria": criteria})


async def api_ingest_propose(request: Request) -> JSONResponse:
    """Étape 2 : rattachement au socle commun (candidats + degré suggéré)."""
    body = await request.json()
    criteria = body.get("criteria") or []
    if not criteria:
        return JSONResponse({"error": "aucune exigence"}, status_code=400)
    proposals = ingest.propose(criteria, limit=INGEST_LIMIT)
    return JSONResponse({"count": len(proposals), "truncated": len(criteria) > INGEST_LIMIT,
                         "proposals": proposals})


async def api_ingest_apply(request: Request) -> JSONResponse:
    """Étape 3 : insertion validée du référentiel."""
    body = await request.json()
    framework = body.get("framework") or {}
    proposals = body.get("proposals") or []
    try:
        result = ingest.apply_framework(framework, proposals, replace=bool(body.get("replace")))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)


# ── Mode connecté : identité Supabase (JWT) → organisation ──────────────────

def _connected_org(request: Request) -> tuple[dict, dict] | None:
    """(user, org) si le Bearer JWT Supabase est valide (org provisionnée au
    besoin), sinon None. Ne lève pas : les appelants renvoient 401 eux-mêmes."""
    try:
        claims = auth.verify_supabase_jwt(auth.bearer_token(request.headers.get("authorization")))
    except auth.AuthError:
        return None
    org = db.org_for_user(claims["sub"], claims.get("email"))
    return claims, org


async def api_auth_me(request: Request) -> JSONResponse:
    """État de connexion du mode « documents » : utilisateur + organisation."""
    res = _connected_org(request)
    if not res:
        return JSONResponse({"user": None, "org": None})
    user, org = res
    return JSONResponse({"user": {"id": user["sub"], "email": user.get("email")}, "org": org})


# ── Authentification par jeton d'organisation (legacy / MCP) ─────────────────

async def api_login(request: Request) -> JSONResponse:
    body = await request.json()
    org = auth.resolve_org(body.get("token", ""))
    if not org:
        return JSONResponse({"error": "Jeton invalide"}, status_code=401)
    request.session["org_id"] = org["id"]
    request.session["org_slug"] = org["slug"]
    request.session["org_name"] = org["name"]
    return JSONResponse({"org": {"slug": org["slug"], "name": org["name"]}})


async def api_logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


async def api_me(request: Request) -> JSONResponse:
    if "org_id" in request.session:
        return JSONResponse({"org": {"slug": request.session["org_slug"], "name": request.session["org_name"]}})
    return JSONResponse({"org": None})


def _org_id(request: Request) -> str | None:
    return request.session.get("org_id")


async def api_assess_start(request: Request) -> JSONResponse:
    org_id = _org_id(request)
    if not org_id:
        return JSONResponse({"error": "authentification requise"}, status_code=401)
    body = await request.json()
    slug = body.get("framework")
    if not db.framework_exists(slug):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=400)
    return JSONResponse({"assessment_id": db.start_assessment(org_id, slug)})


async def api_assess_answer(request: Request) -> JSONResponse:
    org_id = _org_id(request)
    if not org_id:
        return JSONResponse({"error": "authentification requise"}, status_code=401)
    body = await request.json()
    status = body.get("status")
    if status not in VALID_STATUS:
        return JSONResponse({"error": "status invalide"}, status_code=400)
    ok = db.upsert_answer(org_id, body.get("assessment_id"), body.get("common_criterion_id"),
                          status, body.get("note"))
    if not ok:
        return JSONResponse({"error": "évaluation introuvable pour cette organisation"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_assess_result(request: Request) -> JSONResponse:
    org_id = _org_id(request)
    if not org_id:
        return JSONResponse({"error": "authentification requise"}, status_code=401)
    res = db.assessment_result(org_id, request.query_params.get("assessment_id"))
    if not res:
        return JSONResponse({"error": "introuvable"}, status_code=404)
    return JSONResponse(res)


routes = [
    Route("/", landing),
    Route("/console", index),
    Route("/docs", docs),
    Route("/api/frameworks", api_frameworks),
    Route("/api/search", api_search, methods=["POST"]),
    Route("/api/compare", api_compare, methods=["POST"]),
    Route("/api/framework/{slug}", api_framework_detail),
    Route("/api/neighbors/{slug}", api_neighbors),
    Route("/api/pair", api_pair),
    Route("/api/recognition/{scheme}", api_recognition),
    Route("/api/equivalences/{slug}", api_equivalences),
    Route("/api/ingest/extract", api_ingest_extract, methods=["POST"]),
    Route("/api/ingest/propose", api_ingest_propose, methods=["POST"]),
    Route("/api/ingest/apply", api_ingest_apply, methods=["POST"]),
    Route("/api/auth/me", api_auth_me),
    Route("/api/doc-types", api_doc_types),
    Route("/api/doc-types/{slug}/frameworks", api_doc_type_frameworks),
    Route("/api/doc-types/{slug}/frameworks/{fw}/criteria", api_doc_type_criteria),
    Route("/api/common-criterion/{code}", api_common_criterion),
    Route("/api/common-criteria", api_common_criteria),
    Route("/api/login", api_login, methods=["POST"]),
    Route("/api/logout", api_logout, methods=["POST"]),
    Route("/api/me", api_me),
    Route("/api/assessment/start", api_assess_start, methods=["POST"]),
    Route("/api/assessment/answer", api_assess_answer, methods=["POST"]),
    Route("/api/assessment/result", api_assess_result),
]

# Clé de session : depuis .env si présente, sinon éphémère (sessions réinitialisées au redémarrage)
SECRET = os.environ.get("WEB_SECRET_KEY") or secrets.token_hex(32)
middleware = [Middleware(SessionMiddleware, secret_key=SECRET, same_site="lax", https_only=False)]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == "__main__":
    # En conteneur (Coolify), exposer sur 0.0.0.0 via FRAMEKO_WEB_HOST ;
    # par défaut local (127.0.0.1:8080) pour le développement.
    host = os.environ.get("FRAMEKO_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("FRAMEKO_WEB_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")
