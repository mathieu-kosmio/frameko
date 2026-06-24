"""Authentification légère par jeton d'organisation (proto)."""

import hashlib

from mcp_server import db


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def resolve_org(token: str) -> dict | None:
    """Retourne {id, slug, name} pour un jeton valide, sinon None."""
    if not token:
        return None
    return db.query_one(
        "select id::text as id, slug, name from org where token_hash = %s",
        (hash_token(token),),
    )
