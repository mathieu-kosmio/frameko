"""
Frameko — UI web légère (Starlette).

Interface de démonstration locale des trois services : recherche sémantique,
comparaison de référentiels, auto-évaluation de conformité. Réutilise la même
couche d'accès (mcp_server.db) et le même modèle d'embedding que le serveur MCP.

Lancement :
    cd proto
    .venv/bin/python web/app.py            # http://127.0.0.1:8080
"""

import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

PROTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTO))

from mcp_server import db  # noqa: E402
from mcp_server.embeddings import embed_one, to_pgvector  # noqa: E402

WEB = Path(__file__).resolve().parent
VALID_STATUS = {"conforme", "partiel", "non_conforme", "non_applicable"}


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))


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


async def api_assess_start(request: Request) -> JSONResponse:
    body = await request.json()
    slug = body.get("framework")
    if not db.framework_exists(slug):
        return JSONResponse({"error": "référentiel inconnu"}, status_code=400)
    return JSONResponse({"assessment_id": db.start_assessment(slug)})


async def api_assess_answer(request: Request) -> JSONResponse:
    body = await request.json()
    aid = body.get("assessment_id")
    cc_id = body.get("common_criterion_id")
    status = body.get("status")
    if status not in VALID_STATUS:
        return JSONResponse({"error": "status invalide"}, status_code=400)
    db.upsert_answer(aid, cc_id, status, body.get("note"))
    return JSONResponse({"ok": True})


async def api_assess_result(request: Request) -> JSONResponse:
    aid = request.query_params.get("assessment_id")
    res = db.assessment_result(aid)
    if not res:
        return JSONResponse({"error": "introuvable"}, status_code=404)
    return JSONResponse(res)


routes = [
    Route("/", index),
    Route("/api/frameworks", api_frameworks),
    Route("/api/search", api_search, methods=["POST"]),
    Route("/api/compare", api_compare, methods=["POST"]),
    Route("/api/common-criteria", api_common_criteria),
    Route("/api/assessment/start", api_assess_start, methods=["POST"]),
    Route("/api/assessment/answer", api_assess_answer, methods=["POST"]),
    Route("/api/assessment/result", api_assess_result),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
