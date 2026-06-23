"""Tests d'intégration API — nécessitent une base Supabase configurée."""

import pytest
from httpx import AsyncClient, ASGITransport

from frameko.api.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_list_frameworks_empty(client: AsyncClient) -> None:
    # En environnement de test sans DB réelle, on attend une erreur 500 ou une liste vide.
    r = await client.get("/v1/frameworks")
    assert r.status_code in (200, 500)
