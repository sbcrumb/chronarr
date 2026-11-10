"""
Tests for the shared-secret gate on POST /api/instance-migration:
_current_integration_key / _require_integration_key in api/routes.py.
Exercises the real functions against a temp file standing in for
.env.secrets — no FastAPI app or real request needed, just something with
a .headers.get(...).
"""
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import routes


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.fixture
def secrets_file(tmp_path, monkeypatch):
    path = tmp_path / ".env.secrets"
    monkeypatch.setattr(routes, "_SECRETS_PATH", path)
    return path


def test_no_key_configured_refuses_every_call(secrets_file):
    with pytest.raises(HTTPException) as exc:
        routes._require_integration_key(_FakeRequest({"X-Chronarr-Key": "anything"}))
    assert exc.value.status_code == 503


def test_correct_key_is_accepted(secrets_file):
    secrets_file.write_text("CHRONARR_INTEGRATION_KEY=sekret123\n")
    routes._require_integration_key(_FakeRequest({"X-Chronarr-Key": "sekret123"}))  # must not raise


def test_wrong_key_is_refused(secrets_file):
    secrets_file.write_text("CHRONARR_INTEGRATION_KEY=sekret123\n")
    with pytest.raises(HTTPException) as exc:
        routes._require_integration_key(_FakeRequest({"X-Chronarr-Key": "wrong"}))
    assert exc.value.status_code == 403


def test_missing_header_is_refused(secrets_file):
    secrets_file.write_text("CHRONARR_INTEGRATION_KEY=sekret123\n")
    with pytest.raises(HTTPException) as exc:
        routes._require_integration_key(_FakeRequest({}))
    assert exc.value.status_code == 403


def test_set_then_clear_takes_effect_immediately(secrets_file):
    assert routes._current_integration_key() == ""
    routes.upsert_env_file(secrets_file, {routes._INTEGRATION_KEY_ENV: "newkey"})
    assert routes._current_integration_key() == "newkey"
    routes.upsert_env_file(secrets_file, {routes._INTEGRATION_KEY_ENV: ""})
    assert routes._current_integration_key() == ""
