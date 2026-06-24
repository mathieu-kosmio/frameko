"""
Frameko — Serveur MCP (fastmcp).

Expose la connaissance des référentiels à un agent (Claude) :
recherche sémantique d'exigences, proximité inter-référentiels, comparaison de
couverture, et auto-évaluation de conformité. L'embedding de requête est calculé
côté serveur avec le même modèle local que celui des données.

Lancement :
    cd proto
    .venv/bin/python mcp_server/server.py        # transport stdio
"""

import os
import sys
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import auth, db  # noqa: E402
from mcp_server.embeddings import embed_one, to_pgvector  # noqa: E402

mcp = FastMCP("Frameko")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Sonde de vivacité (déploiement / orchestrateur) : vérifie l'accès base."""
    try:
        db.query("select 1 as ok")
        return JSONResponse({"status": "ok", "service": "frameko-mcp"})
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)[:120]}, status_code=503)

VALID_STATUS = {"conforme", "partiel", "non_conforme", "non_applicable"}


# ── S1 — Référentiels ───────────────────────────────────────────────────────

@mcp.tool
def list_frameworks() -> list[dict]:
    """Liste les référentiels disponibles avec leur nombre de critères."""
    return db.list_frameworks()


@mcp.tool
def get_framework(slug: str) -> dict:
    """Détail d'un référentiel (métadonnées + ses critères). `slug` ex. 'florverde'."""
    fw = db.get_framework(slug)
    if not fw:
        return {"error": f"Référentiel inconnu : {slug}"}
    return fw


# ── S2 — Recherche et proximité ─────────────────────────────────────────────

@mcp.tool
def search_requirements(query: str, framework: str | None = None, theme: str | None = None) -> dict:
    """
    Recherche sémantique d'exigences à partir d'un texte libre.
    Retourne les critères communs les plus proches et les critères de référentiel
    voisins, filtrables par `framework` (slug) et/ou `theme` (slug).
    """
    vec = to_pgvector(embed_one(query))

    common = db.match_common(vec, k=8)
    if theme:
        common = [c for c in common if c["theme_slug"] == theme]

    fc = db.nearest_fc(vec, k=40)
    if framework:
        fc = [r for r in fc if r["framework_slug"] == framework]
    if theme:
        # filtre via le thème du critère commun rattaché
        themed_codes = {c["code"] for c in db.match_common(vec, k=51) if c["theme_slug"] == theme}
        fc = [r for r in fc if r["common_code"] in themed_codes]
    fc = fc[:10]

    return {"query": query, "common_criteria": common, "framework_criteria": fc}


@mcp.tool
def nearest_requirements(text: str) -> dict:
    """
    Pour un texte d'exigence, retourne le critère commun de rattachement le plus
    probable et les exigences proches des autres référentiels, avec leur degré.
    """
    vec = to_pgvector(embed_one(text))
    common = db.match_common(vec, k=1)
    neighbors = db.nearest_fc(vec, k=10)
    return {
        "text": text,
        "attaches_to": common[0] if common else None,
        "neighbors": neighbors,
    }


@mcp.tool
def propose_mapping(criterion_text: str, top_k: int = 6) -> dict:
    """
    Ingestion assistée (MCP-first) : pour une exigence nouvelle, propose son
    rattachement au socle commun. Retourne les critères communs candidats (par
    similarité) et des précédents — critères déjà qualifiés proches, avec leur
    degré — pour aider à choisir le degré (equivautA, plusStrictQue,
    plusLargeQue, rapprocheDe). Le choix final est fait par l'agent.
    """
    vec = to_pgvector(embed_one(criterion_text))
    candidates = db.match_common(vec, k=top_k)
    precedents = db.nearest_fc(vec, k=5)
    return {
        "criterion_text": criterion_text,
        "candidates": candidates,
        "precedents": [
            {
                "framework_slug": p["framework_slug"],
                "label": p["label"],
                "common_code": p["common_code"],
                "common_label": p["common_label"],
                "degree": p["degree"],
                "similarity": p["similarity"],
            }
            for p in precedents
        ],
        "degrees": ["equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"],
    }


@mcp.tool
def compare_frameworks(a: str, b: str) -> dict:
    """
    Compare la couverture de deux référentiels (slugs) via les critères communs.
    Retourne le détail par critère commun et un résumé de recouvrement.
    """
    if not db.framework_exists(a):
        return {"error": f"Référentiel inconnu : {a}"}
    if not db.framework_exists(b):
        return {"error": f"Référentiel inconnu : {b}"}
    rows = db.coverage(a, b)
    shared = [r for r in rows if r["count_a"] > 0 and r["count_b"] > 0]
    only_a = [r for r in rows if r["count_a"] > 0 and r["count_b"] == 0]
    only_b = [r for r in rows if r["count_b"] > 0 and r["count_a"] == 0]
    return {
        "framework_a": a,
        "framework_b": b,
        "summary": {
            "communs_partages": len(shared),
            "seulement_a": len(only_a),
            "seulement_b": len(only_b),
        },
        "detail": rows,
    }


# ── S3 — Auto-évaluation (cloisonnée par organisation) ──────────────────────
# L'organisation est résolue à partir de FRAMEKO_ORG_TOKEN (jeton émis par
# scripts/create_org.py). Les données d'évaluation sont isolées par RLS.

def _bearer_token() -> str:
    """Jeton d'organisation. En HTTP (SaaS multi-tenant) : header Authorization Bearer,
    résolu par requête. En stdio (local) : repli sur FRAMEKO_ORG_TOKEN."""
    try:
        # get_http_headers strippe 'authorization' par défaut → l'inclure explicitement
        headers = get_http_headers(include={"authorization"})
        authz = headers.get("authorization") or headers.get("Authorization") or ""
        if authz.lower().startswith("bearer "):
            return authz[7:].strip()
    except Exception:
        pass
    return os.environ.get("FRAMEKO_ORG_TOKEN", "")


def _current_org() -> dict | None:
    return auth.resolve_org(_bearer_token())


_NO_ORG = {"error": "Aucune organisation : définir FRAMEKO_ORG_TOKEN (voir scripts/create_org.py)."}


@mcp.tool
def start_assessment(framework: str) -> dict:
    """Démarre une auto-évaluation pour un référentiel (slug). Retourne l'assessment_id.

    Requiert FRAMEKO_ORG_TOKEN (les évaluations sont cloisonnées par organisation)."""
    org = _current_org()
    if not org:
        return _NO_ORG
    if not db.framework_exists(framework):
        return {"error": f"Référentiel inconnu : {framework}"}
    aid = db.start_assessment(org["id"], framework)
    return {"assessment_id": aid, "framework": framework, "org": org["slug"]}


@mcp.tool
def answer_assessment(
    assessment_id: str, common_criterion_label: str, status: str, note: str | None = None
) -> dict:
    """
    Enregistre une réponse au niveau d'un critère commun (par son libellé exact).
    `status` ∈ {conforme, partiel, non_conforme, non_applicable}. La réponse vaut
    pour tous les référentiels rattachés au même critère commun.
    """
    org = _current_org()
    if not org:
        return _NO_ORG
    if status not in VALID_STATUS:
        return {"error": f"status invalide : {status}. Attendu : {sorted(VALID_STATUS)}"}
    cc = db.common_criterion_by_label(common_criterion_label)
    if not cc:
        return {"error": f"Critère commun introuvable : {common_criterion_label!r}"}
    ok = db.upsert_answer(org["id"], assessment_id, str(cc["id"]), status, note)
    if not ok:
        return {"error": "Auto-évaluation introuvable pour cette organisation."}
    return {"ok": True, "common_code": cc["code"], "status": status}


@mcp.tool
def get_assessment_result(assessment_id: str) -> dict:
    """Taux de couverture et liste des écarts d'une auto-évaluation (de votre organisation)."""
    org = _current_org()
    if not org:
        return _NO_ORG
    res = db.assessment_result(org["id"], assessment_id)
    if not res:
        return {"error": f"Auto-évaluation introuvable : {assessment_id}"}
    return res


def run() -> None:
    """Lance le serveur.

    - stdio (défaut) : un agent local, organisation via FRAMEKO_ORG_TOKEN.
    - http (SaaS)    : service hébergé multi-tenant, organisation par requête
      (header Authorization: Bearer <jeton>). Activé par FRAMEKO_MCP_TRANSPORT=http.
    """
    transport = os.environ.get("FRAMEKO_MCP_TRANSPORT", "stdio")
    if transport in ("http", "streamable-http", "sse"):
        mcp.run(
            transport=transport,
            host=os.environ.get("FRAMEKO_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("FRAMEKO_MCP_PORT", "8765")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    run()
