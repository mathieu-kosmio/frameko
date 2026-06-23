"""S3 — Auto-évaluation de conformité."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from frameko.api.models import (
    AssessmentAnswersBatch,
    AssessmentCreate,
    AssessmentResult,
)
from frameko.db import get_db

router = APIRouter(prefix="/assessments", tags=["S3 — Auto-évaluation"])


@router.post("", response_model=dict)
async def create_assessment(
    body: AssessmentCreate,
    db: AsyncConnection = Depends(get_db),
) -> dict:
    async with db.cursor() as cur:
        await cur.execute(
            "INSERT INTO assessment (org_id, framework_id) VALUES (%s, %s) RETURNING id, created_at",
            [str(body.org_id), str(body.framework_id)],
        )
        row = await cur.fetchone()
    await db.commit()
    return {"id": str(row[0]), "created_at": row[1].isoformat()}  # type: ignore[index]


@router.put("/{assessment_id}/answers", response_model=dict)
async def upsert_answers(
    assessment_id: UUID,
    body: AssessmentAnswersBatch,
    db: AsyncConnection = Depends(get_db),
) -> dict:
    """
    Enregistre les réponses au niveau des critères communs.
    La même réponse sert automatiquement pour tous les référentiels
    rattachés au même critère commun.
    """
    async with db.cursor() as cur:
        row = await cur.fetchone() if False else None  # typecheck trick
        await cur.execute("SELECT id FROM assessment WHERE id = %s", [str(assessment_id)])
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Auto-évaluation introuvable")

        for ans in body.answers:
            await cur.execute(
                """
                INSERT INTO assessment_answer
                    (assessment_id, common_criterion_id, status, note, evidence_url)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (assessment_id, common_criterion_id)
                DO UPDATE SET status = EXCLUDED.status,
                              note = EXCLUDED.note,
                              evidence_url = EXCLUDED.evidence_url
                """,
                [
                    str(assessment_id),
                    str(ans.common_criterion_id),
                    ans.status,
                    ans.note,
                    ans.evidence_url,
                ],
            )
    await db.commit()
    return {"updated": len(body.answers)}


@router.get("/{assessment_id}/result", response_model=AssessmentResult)
async def get_result(
    assessment_id: UUID,
    db: AsyncConnection = Depends(get_db),
) -> AssessmentResult:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT framework_id FROM assessment WHERE id = %s", [str(assessment_id)]
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Auto-évaluation introuvable")
        framework_id = row[0]

        # Nombre total de critères communs couverts par ce référentiel
        await cur.execute(
            """
            SELECT COUNT(DISTINCT m.common_criterion_id)
            FROM mapping m
            JOIN framework_criterion fc ON fc.id = m.framework_criterion_id
            WHERE fc.framework_id = %s
            """,
            [str(framework_id)],
        )
        total = (await cur.fetchone())[0] or 0  # type: ignore[index]

        # Réponses agrégées
        await cur.execute(
            """
            SELECT aa.status, COUNT(*) AS cnt, SUM(cc.weight) AS weighted
            FROM assessment_answer aa
            JOIN common_criterion cc ON cc.id = aa.common_criterion_id
            WHERE aa.assessment_id = %s
            GROUP BY aa.status
            """,
            [str(assessment_id)],
        )
        status_rows = await cur.fetchall()

    counts = {r[0]: (int(r[1]), float(r[2] or 0)) for r in status_rows}
    compliant = counts.get("compliant", (0, 0.0))
    partial = counts.get("partial", (0, 0.0))
    non_compliant = counts.get("non_compliant", (0, 0.0))

    answered = sum(v[0] for v in counts.values())
    weighted_score = compliant[1] + partial[1] * 0.5

    total_weight_q = "SELECT SUM(cc.weight) FROM common_criterion cc" \
                     " JOIN mapping m ON m.common_criterion_id = cc.id" \
                     " JOIN framework_criterion fc ON fc.id = m.framework_criterion_id" \
                     " WHERE fc.framework_id = %s"
    async with db.cursor() as cur:
        await cur.execute(total_weight_q, [str(framework_id)])
        total_weight = float((await cur.fetchone())[0] or 1)  # type: ignore[index]

    score = round(weighted_score / total_weight * 100, 1) if total_weight else 0.0

    # Écarts (non-compliant + partial)
    gaps: list[dict] = []
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT cc.code, cc.label_fr, aa.status, aa.note
            FROM assessment_answer aa
            JOIN common_criterion cc ON cc.id = aa.common_criterion_id
            WHERE aa.assessment_id = %s AND aa.status IN ('non_compliant', 'partial')
            ORDER BY cc.code
            """,
            [str(assessment_id)],
        )
        for r in await cur.fetchall():
            gaps.append({"code": r[0], "label": r[1], "status": r[2], "note": r[3]})

    # Équivalences sur d'autres référentiels (critères communs déjà conformes)
    cross: list[dict] = []
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT f.slug, f.title, COUNT(*) AS shared_compliant
            FROM assessment_answer aa
            JOIN mapping m ON m.common_criterion_id = aa.common_criterion_id
            JOIN framework_criterion fc ON fc.id = m.framework_criterion_id
            JOIN framework f ON f.id = fc.framework_id
            WHERE aa.assessment_id = %s
              AND aa.status = 'compliant'
              AND f.id != %s
            GROUP BY f.slug, f.title
            ORDER BY shared_compliant DESC
            LIMIT 10
            """,
            [str(assessment_id), str(framework_id)],
        )
        for r in await cur.fetchall():
            cross.append({"framework_slug": r[0], "framework_title": r[1], "shared_criteria": int(r[2])})

    return AssessmentResult(
        assessment_id=assessment_id,
        framework_id=framework_id,
        score=score,
        total_criteria=total,
        answered_criteria=answered,
        compliant=compliant[0],
        partial=partial[0],
        non_compliant=non_compliant[0],
        gaps=gaps,
        cross_coverage=cross,
    )
