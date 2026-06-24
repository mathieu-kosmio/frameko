"""
Service d'embedding local — partagé par le script de calcul et le serveur MCP.

Modèle : sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384 dim).
Backend par défaut : fastembed (ONNX, léger, aucune clé API). Bascule possible
plus tard vers un fournisseur hébergé via EMBEDDING_BACKEND.

Variables d'environnement :
    EMBEDDING_MODEL    (défaut : sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
    EMBEDDING_BACKEND  (défaut : fastembed ; alternative : sentence-transformers)
"""

import os
from functools import lru_cache

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
BACKEND = os.environ.get("EMBEDDING_BACKEND", "fastembed")


@lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding

    # Cache du modèle paramétrable (FRAMEKO_MODEL_CACHE) → montable en volume Docker
    cache_dir = os.environ.get("FRAMEKO_MODEL_CACHE") or None
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=cache_dir)


@lru_cache(maxsize=1)
def _sentence_transformers_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Calcule les embeddings d'une liste de textes (vecteurs de 384 floats)."""
    if not texts:
        return []
    if BACKEND == "sentence-transformers":
        model = _sentence_transformers_model()
        return [v.tolist() for v in model.encode(texts, normalize_embeddings=False)]
    # fastembed (défaut)
    model = _fastembed_model()
    return [v.tolist() for v in model.embed(texts)]


def embed_one(text: str) -> list[float]:
    """Calcule l'embedding d'un seul texte."""
    return embed_texts([text])[0]


def to_pgvector(vector: list[float]) -> str:
    """Sérialise un vecteur au format littéral pgvector : '[v1,v2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"
