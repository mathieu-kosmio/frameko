"""Accès au stockage de fichiers Supabase Storage (bucket privé « documents »).

Tout passe par le backend avec la clé service (jamais exposée au navigateur) ;
l'isolation par organisation est assurée en amont (org_id vérifié via le JWT) et
reflétée dans le chemin objet {org_id}/{document_id}/{filename}.

Implémenté avec la bibliothèque standard (urllib) pour éviter toute dépendance
de version au SDK.
"""

import os
import urllib.error
import urllib.request

BUCKET = "documents"


def _base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1/object"


def _headers() -> dict:
    key = os.environ["SUPABASE_SECRET_KEY"]
    return {"Authorization": "Bearer " + key, "apikey": key}


def upload(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Crée/écrase un objet dans le bucket (upsert)."""
    h = _headers() | {"Content-Type": content_type, "x-upsert": "true"}
    req = urllib.request.Request(f"{_base()}/{BUCKET}/{path}", data=data, method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=60):
        return None


def download(path: str) -> bytes:
    req = urllib.request.Request(f"{_base()}/{BUCKET}/{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def remove(path: str) -> None:
    """Supprime un objet ; tolérant si l'objet n'existe plus."""
    req = urllib.request.Request(f"{_base()}/{BUCKET}/{path}", method="DELETE", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30):
            return None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
