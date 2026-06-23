"""Serveur MCP Frameko — expose la connaissance référentiels à des agents IA."""

import json
import logging

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from frameko.config import settings

logger = logging.getLogger(__name__)

API_BASE = f"http://{settings.api_host}:{settings.api_port}/v1"

server = Server("frameko")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_frameworks",
            description="Liste les référentiels de certification disponibles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Filtrer par domaine (slug)"},
                    "status": {"type": "string", "default": "active"},
                },
            },
        ),
        types.Tool(
            name="get_framework",
            description="Retourne les détails et critères d'un référentiel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "UUID du référentiel"},
                },
                "required": ["id"],
            },
        ),
        types.Tool(
            name="search_requirements",
            description=(
                "Recherche sémantique : trouve les critères communs les plus proches "
                "d'un texte libre, avec les exigences équivalentes par référentiel."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texte de l'exigence à rechercher"},
                    "top_k": {"type": "integer", "default": 10},
                    "min_confidence": {"type": "number", "default": 0.5},
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="compare_frameworks",
            description="Matrice de couverture entre deux référentiels via les critères communs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "framework_a": {"type": "string", "description": "UUID du référentiel A"},
                    "framework_b": {"type": "string", "description": "UUID du référentiel B"},
                },
                "required": ["framework_a", "framework_b"],
            },
        ),
        types.Tool(
            name="get_criterion_frameworks",
            description="Tous les critères de référentiel rattachés à un critère commun.",
            inputSchema={
                "type": "object",
                "properties": {
                    "common_criterion_id": {"type": "string"},
                },
                "required": ["common_criterion_id"],
            },
        ),
        types.Tool(
            name="assess_conformity",
            description=(
                "Crée ou met à jour une auto-évaluation. "
                "Les réponses se réutilisent entre référentiels via le socle commun."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assessment_id": {
                        "type": "string",
                        "description": "UUID existant, ou laisser vide pour créer",
                    },
                    "org_id": {"type": "string"},
                    "framework_id": {"type": "string"},
                    "answers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "common_criterion_id": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "compliant",
                                        "partial",
                                        "non_compliant",
                                        "not_applicable",
                                    ],
                                },
                                "note": {"type": "string"},
                            },
                            "required": ["common_criterion_id", "status"],
                        },
                    },
                },
                "required": ["org_id", "framework_id"],
            },
        ),
        types.Tool(
            name="ingest_framework",
            description="Lance l'ingestion d'une nouvelle source (PDF, tableur, URL, RDF).",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_ref": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["pdf", "spreadsheet", "url", "rdf"],
                    },
                    "framework_slug": {"type": "string"},
                },
                "required": ["source_ref", "type"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            result = await _dispatch(client, name, arguments)
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        except httpx.HTTPError as exc:
            return [types.TextContent(type="text", text=f"Erreur API : {exc}")]


async def _dispatch(client: httpx.AsyncClient, name: str, args: dict) -> dict | list:
    if name == "list_frameworks":
        params = {k: v for k, v in args.items() if v is not None}
        r = await client.get(f"{API_BASE}/frameworks", params=params)
        r.raise_for_status()
        return r.json()

    if name == "get_framework":
        r = await client.get(f"{API_BASE}/frameworks/{args['id']}")
        r.raise_for_status()
        return r.json()

    if name == "search_requirements":
        r = await client.post(f"{API_BASE}/match", json=args)
        r.raise_for_status()
        return r.json()

    if name == "compare_frameworks":
        a, b = args["framework_a"], args["framework_b"]
        r = await client.get(f"{API_BASE}/frameworks/{a}/compare/{b}")
        r.raise_for_status()
        return r.json()

    if name == "get_criterion_frameworks":
        cid = args["common_criterion_id"]
        r = await client.get(f"{API_BASE}/common-criteria/{cid}/frameworks")
        r.raise_for_status()
        return r.json()

    if name == "assess_conformity":
        assessment_id = args.get("assessment_id")
        if not assessment_id:
            r = await client.post(
                f"{API_BASE}/assessments",
                json={"org_id": args["org_id"], "framework_id": args["framework_id"]},
            )
            r.raise_for_status()
            assessment_id = r.json()["id"]

        if args.get("answers"):
            r = await client.put(
                f"{API_BASE}/assessments/{assessment_id}/answers",
                json={"answers": args["answers"]},
            )
            r.raise_for_status()

        r = await client.get(f"{API_BASE}/assessments/{assessment_id}/result")
        r.raise_for_status()
        return r.json()

    if name == "ingest_framework":
        r = await client.post(f"{API_BASE}/ingestion-jobs", json=args)
        r.raise_for_status()
        return r.json()

    return {"error": f"Outil inconnu : {name}"}


async def serve() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="frameko",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run() -> None:
    import asyncio
    asyncio.run(serve())


if __name__ == "__main__":
    run()
