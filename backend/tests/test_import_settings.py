"""Import settings: DB overrides, path confinement, PATCH endpoint, poll ticks."""

from unittest.mock import patch

from app.core.config import settings
from app.models.import_draft import ImportDraft
from app.services import app_settings
from app.services.bill_import import (
    poll_directory,
    poll_directory_tick,
    reset_poll_timers,
)
from tests.conftest import auth, register_and_login

EXTRACTED = {
    "provider": "Sydney Water",
    "amount": 87.30,
    "currency": "AUD",
    "due_date": "2026-11-12",
    "period": "2026-10",
    "confidence": 0.9,
}

PNG = b"\x89PNG\r\n\x1a\nsettings-test"


def test_db_overrides_env_and_falls_back(client_db):
    client, db = client_db
    with (
        patch.object(settings, "import_enabled", False),
        patch.object(settings, "import_dir", "/data/env-import"),
        patch.object(settings, "import_poll_minutes", 15),
    ):
        assert app_settings.import_enabled(db) is False
        assert app_settings.import_dir(db) == "/data/env-import"
        assert app_settings.import_poll_minutes(db) == 15

        app_settings.set_value(db, app_settings.IMPORT_ENABLED_KEY, "1")
        app_settings.set_value(db, app_settings.IMPORT_DIR_KEY, "/data/db-import")
        app_settings.set_value(db, app_settings.IMPORT_POLL_MINUTES_KEY, "5")

        assert app_settings.import_enabled(db) is True
        assert app_settings.import_dir(db) == "/data/db-import"
        assert app_settings.import_poll_minutes(db) == 5

        # A junk stored value falls back to the env default.
        app_settings.set_value(db, app_settings.IMPORT_POLL_MINUTES_KEY, "0")
        assert app_settings.import_poll_minutes(db) == 15


def test_path_confinement():
    with patch.object(settings, "data_dir", "/data"):
        assert app_settings.validate_import_dir("/data/import") is None
        assert app_settings.validate_import_dir("/data") is None
        assert app_settings.validate_import_dir("/etc") is not None
        assert app_settings.validate_import_dir("/data/../etc") is not None
        assert app_settings.validate_import_dir("relative/path") is not None
        assert app_settings.validate_import_dir("") is not None


def test_patch_settings_endpoint(client_db):
    client, db = client_db
    token = register_and_login(client, "cfg1@test.com")

    with patch.object(settings, "data_dir", "/data"):
        r = client.patch(
            "/import/settings",
            json={"enabled": True, "directory": "/data/import", "poll_minutes": 5},
            headers=auth(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["import_enabled"] is True
        assert body["import_dir"] == "/data/import"
        assert body["import_poll_minutes"] == 5

        r = client.patch(
            "/import/settings", json={"directory": "/etc"}, headers=auth(token)
        )
        assert r.status_code == 422

        r = client.patch(
            "/import/settings", json={"poll_minutes": 0}, headers=auth(token)
        )
        assert r.status_code == 422

    status = client.get("/import/status", headers=auth(token)).json()
    assert status["import_dir"] == "/data/import"


def test_poll_directory_uses_db_override(client_db, tmp_path):
    client, db = client_db
    register_and_login(client, "cfg2@test.com")

    watch = tmp_path / "import"
    watch.mkdir()
    (watch / "bill.png").write_bytes(PNG)

    with (
        patch.object(settings, "data_dir", str(tmp_path)),
        patch.object(settings, "import_enabled", False),  # env says off
        patch.object(settings, "import_dir", "/data/env-import"),
        patch.object(settings, "import_keep_files", False),
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        app_settings.set_value(db, app_settings.IMPORT_ENABLED_KEY, "1")
        app_settings.set_value(db, app_settings.IMPORT_DIR_KEY, str(watch))

        result = poll_directory(db)
        assert result["processed"] == 1
        assert not (watch / "bill.png").exists()

    assert db.query(ImportDraft).count() == 1


def test_poll_directory_rejects_outside_path(client_db):
    client, db = client_db
    register_and_login(client, "cfg3@test.com")

    with (
        patch.object(settings, "data_dir", "/data"),
        patch.object(settings, "import_enabled", True),
    ):
        app_settings.set_value(db, app_settings.IMPORT_DIR_KEY, "/etc")
        result = poll_directory(db)
    assert result["processed"] == 0
    assert "inside /data" in result["error"]


def test_directory_tick_respects_interval(client_db):
    client, db = client_db
    register_and_login(client, "cfg4@test.com")
    reset_poll_timers()

    with (
        patch.object(settings, "import_enabled", True),
        patch("app.services.bill_import.poll_directory") as mock_poll,
    ):
        poll_directory_tick(db, now=1000.0)
        assert mock_poll.call_count == 1

        # Same interval window: no second run.
        poll_directory_tick(db, now=1060.0)
        assert mock_poll.call_count == 1

        # Interval elapsed (default 15 min): runs again.
        poll_directory_tick(db, now=1000.0 + 15 * 60)
        assert mock_poll.call_count == 2
