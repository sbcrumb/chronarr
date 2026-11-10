"""
Regression test for a real bug: setup.html is served by the chronarr-web
container (register_web_routes), a separate FastAPI app from chronarr-core
(api/routes.py) where /api/settings/integration-key actually lives. The page
calls it as a plain relative fetch, so without a matching proxy route here,
it 404s on whatever's actually serving the page — nothing to do with
rebuilds or hostnames/IPs, the route simply didn't exist on this app.

These exercise the real registered FastAPI routes end-to-end (TestClient),
not just the proxy helper in isolation — this bug was specifically about
wiring/registration, which only an actual route lookup catches.
"""
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.web_routes import register_web_routes


@pytest.fixture
def client():
    app = FastAPI()
    register_web_routes(app, {})
    return TestClient(app)


def _fake_urlopen(response_body: bytes):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = response_body
    cm.__exit__.return_value = False
    return cm


def test_integration_key_status_is_proxied_to_core(client):
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b'{"configured": true}')) as mock_urlopen:
        resp = client.get("/api/settings/integration-key")

    assert resp.status_code == 200
    assert resp.json() == {"configured": True}
    called_url = mock_urlopen.call_args[0][0].full_url
    assert called_url.endswith("/api/settings/integration-key")


def test_integration_key_reveal_query_param_is_forwarded(client):
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b'{"configured": true, "key": "abc123"}')) as mock_urlopen:
        resp = client.get("/api/settings/integration-key?reveal=true")

    assert resp.status_code == 200
    assert resp.json() == {"configured": True, "key": "abc123"}
    called_url = mock_urlopen.call_args[0][0].full_url
    assert called_url.endswith("/api/settings/integration-key?reveal=true")


def test_integration_key_set_is_proxied_to_core_with_body(client):
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b'{"configured": true}')) as mock_urlopen:
        resp = client.post("/api/settings/integration-key", json={"key": "sekret"})

    assert resp.status_code == 200
    assert resp.json() == {"configured": True}
    sent_request = mock_urlopen.call_args[0][0]
    assert sent_request.method == "POST"
    assert sent_request.data == b'{"key": "sekret"}'
