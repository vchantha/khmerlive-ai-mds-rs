from app.auth import providers
from app.main import app

def test_social_routes_registered():
    paths={r.path for r in app.routes}
    assert "/api/auth/me" in paths
    assert "/api/auth/providers" in paths
    assert "/api/auth/login/{provider}" in paths
    assert "/api/auth/link/{provider}" in paths
    assert "/api/auth/callback/{provider}" in paths
    assert "/api/auth/logout" in paths

def test_social_providers_disabled_without_config(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,"google_client_id","")
    monkeypatch.setattr(settings,"google_client_secret","")
    monkeypatch.setattr(settings,"facebook_client_id","")
    monkeypatch.setattr(settings,"facebook_client_secret","")
    assert all(p["enabled"] is False for p in providers())
