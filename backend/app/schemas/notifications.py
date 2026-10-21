from pydantic import BaseModel, Field


class SmtpSettingsIn(BaseModel):
    host: str | None = Field(None, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    user: str | None = Field(None, max_length=255)
    password: str | None = Field(None, max_length=500)
    use_tls: bool | None = None
    from_addr: str | None = Field(None, max_length=255)


class AppriseSettingsIn(BaseModel):
    base_url: str | None = Field(None, max_length=500)
    urls: str | None = Field(None, max_length=2000)
    key: str | None = Field(None, max_length=255)
    timeout_seconds: float | None = Field(None, ge=1, le=300)


class NotificationSettingsIn(BaseModel):
    smtp: SmtpSettingsIn | None = None
    apprise: AppriseSettingsIn | None = None


class NotificationSettingsOut(BaseModel):
    smtp_configured: bool
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password_configured: bool
    smtp_use_tls: bool
    smtp_from: str | None
    apprise_configured: bool
    apprise_base_url: str | None
    apprise_urls_configured: bool
    apprise_key_configured: bool
    apprise_timeout_seconds: float
