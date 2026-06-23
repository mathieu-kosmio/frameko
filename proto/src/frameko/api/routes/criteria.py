"""S1 — Critères communs et critères de référentiel (lecture)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from frameko.api.models import CommonCriterion, FrameworkCriterion
from frameko.db import get_db

router = APIRouter(tags=["S1 — Critères"])


@router.get("/common-criteria", response_model=list[CommonCriterion])
async def list_common_criteria(
    theme: str | None = Query(None),
    db: AsyncConnection = Depends(get_db),
) -> list[CommonCriterion]:
    q = "SELECT id, code, label_fr, label_en, definition, theme_id, iri, weight FROM common_criterion"
    params: list = []
    if theme:
        q += " WHERE theme_id = (SELECT id FROM theme WHERE slug = %s)"
        params.append(theme)
    q += " ORDER BY code"
    async with db.cursor() as cur:
        await cur.execute(q, params)
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return [CommonCriterion(**dict(zip(cols, r))) for r in rows]


@router.get("/common-criteria/{criterion_id}", response_model=CommonCriterion)
async def get_common_criterion(
    criterion_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> CommonCriterion:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, code, label_fr, label_en, definition, theme_id, iri, weight"
            " FROM common_criterion WHERE id = %s",
            [str(criterion_id)],
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Critère commun introuvable")
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return CommonCriterion(**dict(zip(cols, row)))


@router.get("/common-criteria/{criterion_id}/frameworks", response_model=list[dict])
async def get_criterion_frameworks(
    criterion_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> list[dict]:
    """Tous les critères de référentiel rattachés à un critère commun, avec leur degré."""
    query = """
        SELECT
            f.id AS framework_id,
            f.title AS framework_title,
            f.slug AS framework_slug,
            fc.id AS criterion_id,
            fc.reference,
            fc.label,
            fc.level,
            m.degree,
            m.confidence
        FROM mapping m
        JOIN framework_criterion fc ON fc.id = m.framework_criterion_id
        JOIN framework f ON f.id = fc.framework_id
        WHERE m.common_criterion_id = %s
        ORDER BY f.title, fc.reference NULLS LAST
    """
    async with db.cursor() as cur:
        await cur.execute(query, [str(criterion_id)])
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return [dict(zip(cols, r)) for r in rows]


@router.get("/criteria/{criterion_id}", response_model=FrameworkCriterion)
async def get_criterion(
    criterion_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> FrameworkCriterion:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, framework_id, reference, label, theme_id, level, iri,"
            " source_excerpt, is_verbatim_allowed FROM framework_criterion WHERE id = %s",
            [str(criterion_id)],
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Critère introuvable")
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return FrameworkCriterion(**dict(zip(cols, row)))
