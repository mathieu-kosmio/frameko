"""S1 — Référentiels et exigences."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from frameko.api.models import Framework, FrameworkCriterion
from frameko.db import get_db

router = APIRouter(prefix="/frameworks", tags=["S1 — Référentiels"])


@router.get("", response_model=list[Framework])
async def list_frameworks(
    domain: str | None = Query(None),
    status: str = Query("active"),
    db: AsyncConnection = Depends(get_db),
) -> list[Framework]:
    q = "SELECT * FROM framework WHERE status = %s"
    params: list = [status]
    if domain:
        q += " AND domain_id = (SELECT id FROM domain WHERE slug = %s)"
        params.append(domain)
    q += " ORDER BY title"
    async with db.cursor() as cur:
        await cur.execute(q, params)
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return [Framework(**dict(zip(cols, r))) for r in rows]


@router.get("/{framework_id}", response_model=Framework)
async def get_framework(
    framework_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> Framework:
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM framework WHERE id = %s", [str(framework_id)])
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Référentiel introuvable")
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return Framework(**dict(zip(cols, row)))


@router.get("/{framework_id}/criteria", response_model=list[FrameworkCriterion])
async def list_criteria(
    framework_id: UUID,
    theme: str | None = Query(None),
    level: str | None = Query(None),
    db: AsyncConnection = Depends(get_db),
) -> list[FrameworkCriterion]:
    q = "SELECT fc.* FROM framework_criterion fc WHERE fc.framework_id = %s"
    params: list = [str(framework_id)]
    if theme:
        q += " AND fc.theme_id = (SELECT id FROM theme WHERE slug = %s)"
        params.append(theme)
    if level:
        q += " AND fc.level = %s"
        params.append(level)
    q += " ORDER BY fc.reference NULLS LAST, fc.label"
    async with db.cursor() as cur:
        await cur.execute(q, params)
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]
    return [FrameworkCriterion(**dict(zip(cols, r))) for r in rows]


@router.get("/{a}/compare/{b}")
async def compare_frameworks(
    a: UUID,
    b: UUID,
    db: AsyncConnection = Depends(get_db),
) -> dict:
    """Matrice de couverture entre deux référentiels via les critères communs partagés."""
    query = """
        WITH criteria_a AS (
            SELECT fc.id, m.common_criterion_id, m.degree
            FROM framework_criterion fc
            JOIN mapping m ON m.framework_criterion_id = fc.id
            WHERE fc.framework_id = %s
        ),
        criteria_b AS (
            SELECT fc.id, m.common_criterion_id, m.degree
            FROM framework_criterion fc
            JOIN mapping m ON m.framework_criterion_id = fc.id
            WHERE fc.framework_id = %s
        ),
        shared AS (
            SELECT a.common_criterion_id, a.degree AS degree_a, b.degree AS degree_b
            FROM criteria_a a
            JOIN criteria_b b USING (common_criterion_id)
        )
        SELECT
            (SELECT COUNT(*) FROM criteria_a) AS total_a,
            (SELECT COUNT(*) FROM criteria_b) AS total_b,
            COUNT(*) AS shared_count,
            json_agg(json_build_object(
                'common_criterion_id', shared.common_criterion_id,
                'degree_a', shared.degree_a,
                'degree_b', shared.degree_b
            )) AS overlaps
        FROM shared
    """
    async with db.cursor() as cur:
        await cur.execute(query, [str(a), str(b)])
        row = await cur.fetchone()
        if not row:
            return {"total_a": 0, "total_b": 0, "shared_count": 0, "coverage_pct": 0.0}
    total_a, total_b, shared, overlaps = row
    coverage = round(shared / total_a * 100, 1) if total_a else 0.0
    return {
        "framework_a": str(a),
        "framework_b": str(b),
        "total_criteria_a": total_a,
        "total_criteria_b": total_b,
        "shared_common_criteria": shared,
        "coverage_a_in_b_pct": coverage,
        "overlaps": overlaps or [],
    }
