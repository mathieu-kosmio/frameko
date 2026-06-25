"""Authentification du proto.

Deux mécanismes coexistent :
- jeton d'organisation opaque (MCP, legacy) → hash_token / resolve_org ;
- identité Supabase (mode connecté web) → verify_supabase_jwt, puis résolution
  de l'organisation de l'utilisateur via la table org_member.
"""

import hashlib
import os

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


# ── Identité Supabase (mode connecté) ────────────────────────────────────────

class AuthError(Exception):
    """Jeton Supabase absent, invalide ou expiré."""


_jwks_client = None


def _jwks() -> "object":
    """Client JWKS (mis en cache) pointant sur le projet Supabase."""
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        base = os.environ.get("SUPABASE_URL")
        if not base:
            raise AuthError("SUPABASE_URL absent de l'environnement")
        _jwks_client = PyJWKClient(base.rstrip("/") + "/auth/v1/.well-known/jwks.json")
    return _jwks_client


def verify_supabase_jwt(token: str) -> dict:
    """Vérifie un jeton d'accès Supabase et retourne {sub, email}. Lève AuthError
    si le jeton est invalide/expiré.

    Supporte les deux schémas de signature Supabase, choisis d'après l'en-tête
    `alg` du jeton :
    - **asymétrique** (ES256/RS256, défaut des projets récents) → clé publique
      récupérée via le JWKS du projet (SUPABASE_URL/auth/v1/.well-known/jwks.json) ;
    - **HS256** (legacy) → secret partagé SUPABASE_JWT_SECRET
      (Dashboard → Project Settings → API → JWT Secret).
    """
    import jwt  # PyJWT

    if not token:
        raise AuthError("jeton manquant")
    try:
        alg = (jwt.get_unverified_header(token) or {}).get("alg", "")
    except jwt.PyJWTError as exc:
        raise AuthError(f"en-tête de jeton illisible : {exc}") from exc

    try:
        if alg.startswith("HS"):
            secret = os.environ.get("SUPABASE_JWT_SECRET")
            if not secret:
                raise AuthError("SUPABASE_JWT_SECRET absent (jeton HS256)")
            key, algs = secret, ["HS256"]
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
            algs = [alg] if alg else ["ES256", "RS256"]
        claims = jwt.decode(token, key, algorithms=algs, audience="authenticated")
    except AuthError:
        raise
    except jwt.PyJWTError as exc:
        raise AuthError(f"jeton invalide : {exc}") from exc
    except Exception as exc:  # JWKS injoignable, etc.
        raise AuthError(f"vérification impossible : {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("jeton sans identifiant (sub)")
    return {"sub": sub, "email": claims.get("email")}


def bearer_token(authorization: str | None) -> str | None:
    """Extrait le jeton d'un en-tête « Authorization: Bearer <token> »."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None
