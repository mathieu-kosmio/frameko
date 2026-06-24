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

from mcp_server import auth, db  # noqa: E402
from mcp_server.embeddings import embed_one, to_pgvector  # noqa: E402

WEB = Path(__file__).resolve().parent
VALID_STATUS = {"conforme", "partiel", "non_conforme", "non_applicable"}


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))


async def docs(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "docs.html").read_text(encoding="utf-8"))


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


# ── Authentification par jeton d'organisation ───────────────────────────────

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
    Route("/", index),
    Route("/docs", docs),
    Route("/api/frameworks", api_frameworks),
    Route("/api/search", api_search, methods=["POST"]),
    Route("/api/compare", api_compare, methods=["POST"]),
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
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
