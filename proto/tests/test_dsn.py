"""Tests de la résolution de chaîne de connexion (pooler vs direct).

Logique pure — ne nécessite pas de base de données. Garantit que le piège
« endpoint direct IPv6 injoignable en IPv4 » reste neutralisé : flag tolérant,
préférence pooler symétrique pour les deux pools, host loggué sans secret.
"""

import pytest

from mcp_server import db


def test_truthy_accepts_common_forms():
    assert db._truthy("1") and db._truthy("true") and db._truthy("  Yes ") and db._truthy("ON")
    assert not db._truthy("0") and not db._truthy("") and not db._truthy(None) and not db._truthy("false")


def test_resolve_prefers_pooler_when_enabled(monkeypatch):
    monkeypatch.setenv("USE_POOLER", "true")  # forme non « 1 » volontairement
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.ref.supabase.co:5432/postgres")
    monkeypatch.setenv("DATABASE_POOLER_URL", "postgresql://u.ref:p@aws-1-eu.pooler.supabase.com:5432/postgres")
    assert "pooler.supabase.com" in db._resolve_dsn("DATABASE_URL", "DATABASE_POOLER_URL")


def test_resolve_uses_direct_when_disabled(monkeypatch):
    monkeypatch.setenv("USE_POOLER", "0")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.ref.supabase.co:5432/postgres")
    monkeypatch.setenv("DATABASE_POOLER_URL", "postgresql://u.ref:p@aws-1-eu.pooler.supabase.com:5432/postgres")
    assert "db.ref.supabase.co" in db._resolve_dsn("DATABASE_URL", "DATABASE_POOLER_URL")


def test_resolve_falls_back_when_pooler_missing(monkeypatch):
    monkeypatch.setenv("USE_POOLER", "1")
    monkeypatch.delenv("DATABASE_POOLER_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.ref.supabase.co:5432/postgres")
    assert "db.ref.supabase.co" in db._resolve_dsn("DATABASE_URL", "DATABASE_POOLER_URL")


def test_resolve_required_raises_when_absent(monkeypatch):
    monkeypatch.delenv("USE_POOLER", raising=False)
    monkeypatch.delenv("MISSING_DIRECT", raising=False)
    monkeypatch.delenv("MISSING_POOLER", raising=False)
    with pytest.raises(RuntimeError):
        db._resolve_dsn("MISSING_DIRECT", "MISSING_POOLER")


def test_host_hint_hides_credentials():
    hint = db._host_hint("postgresql://user:s3cret@aws-1-eu.pooler.supabase.com:5432/postgres")
    assert "s3cret" not in hint and "user" not in hint
    assert "aws-1-eu.pooler.supabase.com:5432" in hint
