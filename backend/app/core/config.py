import warnings
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "changeme-use-a-long-random-string"
_MIN_JWT_SECRET_LENGTH = 32
_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "sqlite:////data/platybill.db"

    # Root of the mounted data volume; import paths are confined to it.
    data_dir: str = "/data"

    environment: str = "development"
    cookie_secure: bool = False
    trust_proxy: bool = False

    # Per-scope rate limits (in-memory sliding window, single process)
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    login_account_rate_limit: int = 10
    login_account_rate_window_seconds: int = 900
    register_rate_limit: int = 25
    register_rate_window_seconds: int = 3600
    forgot_password_rate_limit: int = 5
    forgot_password_rate_window_seconds: int = 3600
    reset_password_rate_limit: int = 5
    reset_password_rate_window_seconds: int = 600
    change_password_rate_limit: int = 5
    change_password_rate_window_seconds: int = 3600
    change_email_rate_limit: int = 5
    change_email_rate_window_seconds: int = 3600
    send_now_rate_limit: int = 2
    send_now_rate_window_seconds: int = 3600
    restore_rate_limit: int = 5
    restore_rate_window_seconds: int = 3600

    jwt_secret: SecretStr = SecretStr(_DEFAULT_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # CORS — JSON array in env var, e.g. ALLOWED_ORIGINS=["https://app.example.com"]
    allowed_origins: list[str] = ["http://localhost:3010", "http://localhost:3000"]

    # SMTP (optional)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    reminder_from: str | None = None

    # Apprise (optional notification channel, preferred over email when configured)
    apprise_base_url: str | None = None
    apprise_urls: str | None = None
    apprise_key: str | None = None
    apprise_timeout_seconds: float = 10.0

    # Email domain blocklist — addresses whose domain matches are silently skipped
    # by the reminder/summary scheduler. Set via EMAIL_BLOCKED_DOMAINS as a JSON
    # array, e.g. '["test.com","example.com"]'. Defaults cover E2E test addresses.
    email_blocked_domains: list[str] = ["test.com", "example.com"]

    # --- Bill import (optional) -------------------------------------------
    # Local Ollama extraction; uploads always work when Ollama is configured,
    # the directory/email pollers additionally require IMPORT_ENABLED.
    import_enabled: bool = False
    import_user_email: str | None = None  # target account for polled imports
    ollama_base_url: str | None = None
    ollama_model: str = "gemma4"
    ollama_ocr_model: str = "maternion/LightOnOCR-2:1b"
    ollama_text_model: str = "gemma4"
    ollama_timeout_seconds: float = 120.0
    # LLM provider: ollama | openai | anthropic | google | opencode
    # (OpenAI-compatible endpoint). DB keys (llm.*) override these.
    llm_provider: str = "ollama"
    llm_model: str = "gemma4"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120.0
    import_dir: str = "/data/import"
    import_poll_minutes: int = 15
    import_max_file_mb: int = 15
    import_keep_files: bool = False
    import_rate_limit: int = 10
    import_rate_window_seconds: int = 3600

    # IMAP mailbox (optional; part of bill import)
    imap_host: str | None = None
    imap_port: int = 993
    imap_user: str | None = None
    imap_password: SecretStr | None = None
    imap_folder: str = "INBOX"
    imap_tls: bool = True
    imap_poll_minutes: int = 15
    imap_mark_read: bool = True
    imap_allowed_senders: list[str] = []

    # Password reset
    app_base_url: str = "http://localhost:3010"
    password_reset_token_expire_minutes: int = 60

    # Restore safety net — how long a pre-restore snapshot stays recoverable
    restore_snapshot_retention_days: int = 7

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def apprise_configured(self) -> bool:
        # The gateway base URL alone is enough: the container may hold the
        # targets itself (its own APPRISE_STATELESS_URLS or saved config key).
        return bool(self.apprise_base_url)

    @property
    def ollama_configured(self) -> bool:
        return bool(self.ollama_base_url)

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @field_validator("ollama_base_url")
    @classmethod
    def strip_ollama_base_url_trailing_slash(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.rstrip("/")

    @field_validator("apprise_base_url")
    @classmethod
    def strip_apprise_base_url_trailing_slash(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.rstrip("/")

    @field_validator("password_reset_token_expire_minutes")
    @classmethod
    def warn_if_no_token_expiry(cls, v: int) -> int:
        if v == 0:
            warnings.warn(
                "PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=0: reset tokens never expire. "
                "Only use this in development/testing.",
                stacklevel=2,
            )
        return v

    @field_validator("jwt_algorithm")
    @classmethod
    def jwt_algorithm_must_be_hmac(cls, v: str) -> str:
        if v not in _ALLOWED_JWT_ALGORITHMS:
            allowed = ", ".join(sorted(_ALLOWED_JWT_ALGORITHMS))
            raise ValueError(f"JWT_ALGORITHM must be one of: {allowed}")
        return v

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if self.is_production:
            if secret == _DEFAULT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET is set to the default placeholder. "
                    "Set a strong random value via the JWT_SECRET environment variable."
                )
            if len(secret) < _MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET must be at least {_MIN_JWT_SECRET_LENGTH} characters "
                    "in production."
                )
        elif secret == _DEFAULT_JWT_SECRET or len(secret) < _MIN_JWT_SECRET_LENGTH:
            warnings.warn(
                "JWT_SECRET is weak (default placeholder or shorter than "
                f"{_MIN_JWT_SECRET_LENGTH} characters) — insecure for production.",
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def warn_if_insecure_cookie_over_https(self) -> "Settings":
        if not self.cookie_secure and self.app_base_url.lower().startswith("https://"):
            warnings.warn(
                f"APP_BASE_URL ({self.app_base_url}) is HTTPS but COOKIE_SECURE=false. "
                "Session cookies are not marked Secure and can leak over plaintext "
                "connections; set COOKIE_SECURE=true when serving over HTTPS.",
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def warn_if_secure_cookie_over_http(self) -> "Settings":
        if not self.cookie_secure:
            return self
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if (
            self.app_base_url.lower().startswith("http://")
            and urlparse(self.app_base_url).hostname not in local_hosts
        ):
            warnings.warn(
                f"COOKIE_SECURE=true but APP_BASE_URL ({self.app_base_url}) is "
                "plain HTTP. Browsers reject Secure cookies over HTTP, so login "
                "appears to succeed but every request bounces back to /login. "
                "Serve over HTTPS or set COOKIE_SECURE=false.",
                stacklevel=2,
            )
        return self


settings = Settings()
