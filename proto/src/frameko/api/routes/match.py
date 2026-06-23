"""S2 — Proximité et analyse croisée (recherche vectorielle + graphe)."""

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from frameko.api.models import MatchRequest, MatchResult, CommonCriterion
from frameko.db import get_db
from frameko.services.embeddings import embed_text

router = APIRouter(prefix="/match", tags=["S2 — Proximité"])


@router.post("", response_model=list[MatchResult])
async def match_requirements(
    req: MatchRequest,
    db: AsyncConnection = Depends(get_db),
) -> list[MatchResult]:
    """
    Recherche les critères communs les plus proches d'un texte libre,
    puis pour chaque critère commun retourne les exigences voisines
    dans tous les référentiels (via les mappings).
    """
    embedding = await embed_text(req.text)
    if embedding is None:
        raise HTTPException(503, "Service d'embedding indisponible")

    query = """
        SELECT
            cc.id, cc.code, cc.label_fr, cc.label_en, cc.definition,
            cc.theme_id, cc.iri, cc.weight,
            1 - (cc.embedding <=> %s::vector) AS similarity
        FROM common_criterion cc
        WHERE cc.embedding IS NOT NULL
        ORDER BY cc.embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = f"[{','.join(str(x) for x in embedding)}]"

    async with db.cursor() as cur:
        await cur.execute(query, [vec_str, vec_str, req.top_k])
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]  # type: ignore[union-attr]

    results = []
    for row in rows:
        d = dict(zip(cols, row))
        similarity = float(d.pop("similarity"))
        if similarity < req.min_confidence:
            continue

        cc = CommonCriterion(**d)

        # Voisins dans les référentiels via mappings
        async with db.cursor() as cur:
            await cur.execute(
                """
                SELECT f.title AS framework, fc.reference, fc.label, m.degree
                FROM mapping m
                JOIN framework_criterion fc ON fc.id = m.framework_criterion_id
                JOIN framework f ON f.id = fc.framework_id
                WHERE m.common_criterion_id = %s
                ORDER BY f.title
                LIMIT 20
                """,
                [str(cc.id)],
            )
            neighbor_rows = await cur.fetchall()
            neighbor_cols = [d.name for d in cur.description]  # type: ignore[union-attr]

        neighbors = [dict(zip(neighbor_cols, r)) for r in neighbor_rows]
        results.append(MatchResult(common_criterion=cc, similarity=similarity, neighbors=neighbors))

    return results
