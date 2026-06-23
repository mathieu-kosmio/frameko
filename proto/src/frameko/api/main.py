"""Point d'entrée FastAPI — Frameko prototype."""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from frameko.api.routes import assessments, criteria, export, frameworks, ingestion, match
from frameko.config import settings
from frameko.db.client import close_pool, init_pool, init_supabase, set_supabase

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Frameko API",
    description="Plateforme d'agrégation de référentiels de certification",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await init_pool()
    client = await init_supabase()
    set_supabase(client)


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pool()


# Routes v1
PREFIX = "/v1"
app.include_router(frameworks.router, prefix=PREFIX)
app.include_router(criteria.router, prefix=PREFIX)
app.include_router(match.router, prefix=PREFIX)
app.include_router(assessments.router, prefix=PREFIX)
app.include_router(ingestion.router, prefix=PREFIX)
app.include_router(export.router, prefix=PREFIX)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "Frameko API", "version": "0.1.0", "docs": "/docs"}


@app.get("/health", tags=["Ops"])
async def health() -> dict:
    return {"status": "ok"}


def run() -> None:
    uvicorn.run("frameko.api.main:app", host=settings.api_host, port=settings.api_port, reload=True)


if __name__ == "__main__":
    run()
