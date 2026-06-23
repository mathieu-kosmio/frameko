"""Export — Turtle, JSON-LD, CSV."""

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from psycopg import AsyncConnection

from frameko.db import get_db

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("")
async def export(
    format: Literal["turtle", "jsonld", "csv"] = Query("csv"),
    framework: str | None = Query(None),
    db: AsyncConnection = Depends(get_db),
) -> StreamingResponse | PlainTextResponse:
    if format == "csv":
        return await _export_csv(framework, db)
    if format == "turtle":
        return await _export_turtle(framework, db)
    raise HTTPException(400, f"Format '{format}' non supporté pour l'instant")


async def _export_csv(
    framework_slug: str | None, db: AsyncConnection
) -> StreamingResponse:
    q = """
        SELECT
            f.slug AS framework, f.title AS framework_title,
            fc.reference, fc.label AS criterion_label, fc.level,
            t.slug AS theme, cc.code AS common_code, cc.label_fr AS common_label,
            m.degree, m.confidence
        FROM framework_criterion fc
        JOIN framework f ON f.id = fc.framework_id
        LEFT JOIN mapping m ON m.framework_criterion_id = fc.id
        LEFT JOIN common_criterion cc ON cc.id = m.common_criterion_id
        LEFT JOIN theme t ON t.id = fc.theme_id
    """
    params: list = []
    if framework_slug:
        q += " WHERE f.slug = %s"
        params.append(framework_slug)
    q += " ORDER BY f.slug, fc.reference NULLS LAST"

    async with db.cursor() as cur:
        await cur.execute(q, params)
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for row in rows:
        writer.writerow(row)
    buf.seek(0)

    filename = f"frameko_{framework_slug or 'all'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


async def _export_turtle(
    framework_slug: str | None, db: AsyncConnection
) -> PlainTextResponse:
    """Export Turtle minimal des critères et mappings."""
    lines = [
        "@prefix flo: <https://ontology.kosm.io/floriscore/ref#> .",
        "@prefix cccev: <http://data.europa.eu/m8g/> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
    ]

    q = """
        SELECT cc.iri, cc.code, cc.label_fr, cc.label_en
        FROM common_criterion cc ORDER BY cc.code
    """
    async with db.cursor() as cur:
        await cur.execute(q)
        for iri, code, label_fr, label_en in await cur.fetchall():
            if not iri:
                continue
            lines.append(f"<{iri}> a flo:CritereCommun, cccev:Criterion ;")
            lines.append(f'    skos:notation "{code}" ;')
            lines.append(f'    rdfs:label "{label_fr}"@fr ;')
            if label_en:
                lines.append(f'    rdfs:label "{label_en}"@en ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")

    return PlainTextResponse("\n".join(lines), media_type="text/turtle")
