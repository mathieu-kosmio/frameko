"""Ingestion et curation — dépôt et suivi des sources à analyser."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from frameko.api.models import IngestionJob, IngestionJobCreate
from frameko.db import get_db

router = APIRouter(prefix="/ingestion-jobs", tags=["Ingestion"])


@router.post("", response_model=IngestionJob)
async def create_job(
    body: IngestionJobCreate,
    db: AsyncConnection = Depends(get_db),
) -> IngestionJob:
    framework_id = None
    if body.framework_slug:
        async with db.cursor() as cur:
            await cur.execute(
                "SELECT id FROM framework WHERE slug = %s", [body.framework_slug]
            )
            row = await cur.fetchone()
            if row:
                framework_id = row[0]

    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO ingestion_job (source_ref, type, framework_id)
            VALUES (%s, %s, %s)
            RETURNING id, source_ref, type, status, log, framework_id, created_at
            """,
            [body.source_ref, body.type, str(framework_id) if framework_id else None],
        )
        row = await cur.fetchone()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    await db.commit()
    return IngestionJob(**dict(zip(cols, row)))  # type: ignore[arg-type]


@router.get("/{job_id}", response_model=IngestionJob)
async def get_job(
    job_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> IngestionJob:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, source_ref, type, status, log, framework_id, created_at"
            " FROM ingestion_job WHERE id = %s",
            [str(job_id)],
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Job introuvable")
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return IngestionJob(**dict(zip(cols, row)))
