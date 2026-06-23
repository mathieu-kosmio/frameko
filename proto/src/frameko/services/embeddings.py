"""Service d'embedding — OpenAI-compatible via Anthropic ou fallback nul."""

import logging

from frameko.config import settings

logger = logging.getLogger(__name__)


async def embed_text(text: str) -> list[float] | None:
    """
    Calcule l'embedding d'un texte.
    Retourne None si le service est indisponible (pas de clé API configurée).
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY non configuré — embedding indisponible")
        return None

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        # Claude ne fournit pas d'API d'embedding direct ;
        # on utilise un appel text_embedding via le batch API si disponible,
        # sinon on délègue à un modèle d'embedding externe (à brancher en V2).
        # En prototype : retourne None pour signaler l'indisponibilité.
        logger.info("Embedding via Anthropic non encore supporté nativement — retour None")
        return None
    except Exception as exc:
        logger.error("Erreur embedding : %s", exc)
        return None


async def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Calcule les embeddings d'une liste de textes."""
    return [await embed_text(t) for t in texts]
