"""Integration tests for /notifications/settings and provider settings in /import."""

from tests.conftest import auth, register_and_login


def test_notification_settings_round_trip(client):
    token = register_and_login(client, "notif_settings@test.com")

    r = client.get("/notifications/settings", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["smtp_configured"] is False
    assert body["apprise_configured"] is False

    r = client.patch(
        "/notifications/settings",
        json={
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "password": "s3cret",
                "use_tls": True,
                "from_addr": "platybill@example.com",
            },
            "apprise": {"base_url": "http://apprise.test:8000"},
        },
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["smtp_configured"] is True
    assert body["smtp_host"] == "smtp.example.com"
    assert body["smtp_user"] == "bot@example.com"
    assert body["smtp_password_configured"] is True
    assert "s3cret" not in r.text
    assert body["apprise_configured"] is True
    assert body["apprise_base_url"] == "http://apprise.test:8000"

    # Clearing a host unconfigures the channel again.
    r = client.patch(
        "/notifications/settings",
        json={"smtp": {"host": ""}},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["smtp_configured"] is False


def test_import_settings_llm_provider_round_trip(client):
    token = register_and_login(client, "llm_settings@test.com")

    r = client.patch(
        "/import/settings",
        json={
            "llm_provider": "opencode",
            "llm_model": "opencode",
            "llm_base_url": "http://localhost:11434/v1",
        },
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_provider"] == "opencode"
    assert body["llm_model"] == "opencode"
    assert body["llm_base_url"] == "http://localhost:11434/v1"
    assert body["llm_configured"] is True

    r = client.patch(
        "/import/settings", json={"llm_provider": "wat"}, headers=auth(token)
    )
    assert r.status_code == 422, r.text


def test_import_settings_imap_round_trip(client):
    token = register_and_login(client, "imap_settings@test.com")

    r = client.patch(
        "/import/settings",
        json={
            "imap_host": "imap.example.com",
            "imap_user": "me@example.com",
            "imap_password": "s3cret",
            "imap_folder": "Bills",
            "imap_tls": True,
            "imap_poll_minutes": 30,
            "imap_mark_read": False,
        },
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imap_configured"] is True
    assert body["imap_host"] == "imap.example.com"
    assert body["imap_user"] == "m***@example.com"
    assert body["imap_folder"] == "Bills"
    assert body["imap_poll_minutes"] == 30
    assert body["imap_mark_read"] is False
    assert body["imap_password_configured"] is True
    assert "s3cret" not in r.text


def test_server_url_allows_local_and_lan():
    from app.services.app_settings import validate_server_url

    for url in [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://10.112.200.20:11434",
        "http://192.168.1.50:11434",
        "http://ollama:11434",
        "https://api.openai.com/v1",
    ]:
        assert validate_server_url(url) is None, url


def test_server_url_blocks_metadata_and_credentials():
    from app.services.app_settings import validate_server_url

    assert (
        validate_server_url("http://169.254.169.254/latest/meta-data")
        == "URL host is not allowed"
    )
    assert (
        validate_server_url("http://metadata.google.internal/")
        == "URL host is not allowed"
    )
    assert (
        validate_server_url("http://user:pass@host:11434")
        == "URL must not include credentials"
    )
    assert (
        validate_server_url("gopher://host:70")
        == "URL must start with http:// or https://"
    )


def test_global_settings_fail_closed_for_multi_user_without_import_email(client):
    token1 = register_and_login(client, "owner1@test.com")
    token2 = register_and_login(client, "owner2@test.com")

    for token in (token1, token2):
        assert client.get("/import/status", headers=auth(token)).status_code == 403
        assert (
            client.patch(
                "/import/settings", json={"enabled": True}, headers=auth(token)
            ).status_code
            == 403
        )
        assert client.post("/import/scan-now", headers=auth(token)).status_code == 403
        assert (
            client.get("/notifications/settings", headers=auth(token)).status_code
            == 403
        )
        assert (
            client.patch(
                "/notifications/settings",
                json={"smtp": {"host": "evil.example.com"}},
                headers=auth(token),
            ).status_code
            == 403
        )


def test_changing_host_clears_saved_credentials(client):
    token = register_and_login(client, "credclear@test.com")

    # Set SMTP + IMAP + LLM credentials
    r1 = client.patch(
        "/notifications/settings",
        json={"smtp": {"host": "smtp.a.test", "password": "secret1"}},
        headers=auth(token),
    )
    assert r1.status_code == 200
    assert r1.json()["smtp_password_configured"] is True

    # Changing SMTP host without supplying a new password clears the saved password
    r2 = client.patch(
        "/notifications/settings",
        json={"smtp": {"host": "smtp.b.test"}},
        headers=auth(token),
    )
    assert r2.status_code == 200
    assert r2.json()["smtp_password_configured"] is False

    # Same for IMAP and LLM base URL
    r3 = client.patch(
        "/import/settings",
        json={
            "imap_host": "imap.a.test",
            "imap_user": "u@a.test",
            "imap_password": "secret2",
            "llm_provider": "opencode",
            "llm_base_url": "http://llm-a.test/v1",
            "llm_api_key": "secret3",
        },
        headers=auth(token),
    )
    assert r3.status_code == 200
    assert r3.json()["imap_password_configured"] is True
    assert r3.json()["llm_api_key_configured"] is True

    r4 = client.patch(
        "/import/settings",
        json={
            "imap_host": "imap.b.test",
            "llm_base_url": "http://llm-b.test/v1",
        },
        headers=auth(token),
    )
    assert r4.status_code == 200
    assert r4.json()["imap_password_configured"] is False
    assert r4.json()["llm_api_key_configured"] is False
