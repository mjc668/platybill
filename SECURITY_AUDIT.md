# Security & Functionality Audit — Platybill

Date: 2026-05-21 (audit performed against current working tree)

## Summary

The codebase is well-structured with strong fundamentals: SQLAlchemy 2.0 ORM, JWT with issuer/audience + `token_version` revocation, bcrypt password hashing, exact-money `Money` type, UTC-normalized timestamps, idempotent recurrence on `(bill_id, due_date)`, draft-first imports, and pre-restore snapshots. The highest-value fixes are SSRF hardening on the Ollama URL, import-path symlink confinement, and authorization on global import settings.

---

## Security Findings

### P0 — Critical/High

| # | Area | Finding | Recommendation |
|---|------|---------|----------------|
| S1 | Import settings | Any authenticated user can mutate global app settings (Ollama URL, import dir/enabled, poll interval). No admin/role model. | Restrict to owner/admin or make settings per-user; require re-auth for changes. |
| S2 | SSRF | Ollama base URL is user-controlled and only scheme-validated; server calls arbitrary hosts. | Allowlist/block private, loopback, link-local, metadata IPs; validate DNS resolution. |
| S3 | Filesystem | Directory poller follows symlinks inside `IMPORT_DIR`; path confinement validates the dir, not each file. | Resolve each file and verify it stays under `DATA_DIR`; use `O_NOFOLLOW`. |

### P1 — Medium

| # | Area | Finding | Recommendation |
|---|------|---------|----------------|
| S4 | Rate limiting | Default `TRUST_PROXY=false` collapses all traffic to `127.0.0.1` behind the Next proxy, making IP limits global. | Pass a trusted client IP from Next or document `TRUST_PROXY` usage behind a real proxy. |
| S5 | Account enumeration | `forgot-password` timing differs when the user exists (token write + optional SMTP). | Normalize timing/response. |
| S6 | Reset password | `ResetPasswordRequest` only rejects oversized passwords; backend calls strength check, but schema parity is weaker than register/change-password. | Add `validate_password_strength` to the schema. |

### Low / Informational

- No CSRF token — mitigated by `SameSite=Lax` and same-origin proxy.
- In-memory rate limiter is single-process only.
- No MFA or email verification.
- SQLite at rest is not DB-encrypted; rely on volume/disk encryption.
- `/health` is unauthenticated (expected).
- Demo credentials only seeded via demo profile.

### Done well

- JWT: issuer/audience, algorithm allowlist, `token_version` revocation, strong-secret enforcement in production.
- bcrypt with 72-byte guard; safe verify on malformed hash.
- ORM avoids SQL injection; money stored as integer cents; timestamps UTC-normalized.
- Uploads and import dirs are size/type/path constrained.
- Security headers (CSP nonce, HSTS, frame-ancestors, etc.) in `proxy.ts`.
- Soft-delete/archive rules enforced; restore takes a pre-restore snapshot.
- PII masked in logs; HTML escaped in email templates.

---

## Functionality Assessment

### Backend

- Recurrence idempotent on `(bill_id, due_date)`; weekly/monthly/annual/one-off handled; cap pruning present.
- Payment ledger derives status/paid_amount/paid_at; partial payments supported; revert clears events.
- Variable bills: estimates + confirmation; suggested amount from median of last 3.
- Archive/unarchive cancels occurrences in archived span and resumes from today.
- Imports are draft-first with dedup by `source_ref`.
- Reminders: per-user timezone, blocked domains, channel fallback (Apprise → SMTP).
- Minor issue: `PaymentCreate.paid_on` uses server `date.today()` instead of `user_today(me.timezone)`.
- Minor issue: `sync_instances` only seeds when `target >= current_month`.

### Frontend

- App Router only; no `pages/` dir.
- Cookie-based auth, `sessionStorage` expiry flag, proxy redirect handling; hydration-safe.
- API base/prefix resolved at runtime from injected env.
- CSP nonce-based scripts; SW passthrough for installability.
- Gap: no automated frontend tests (Playwright config exists but coverage unclear).

### Cross-cutting

- Money: integer cents via `Money` decorator.
- Timestamps: `UTCDateTime` normalizes to UTC naive storage.
- Timezones: `user_today` used in most paths (exception noted above).
- SQLite: WAL, foreign keys ON, busy_timeout 5000.
- Migrations: batch mode; pre-migration snapshot via backup API.

---

## Gap / Omission Analysis

- No admin/role model; global settings mutable by any user.
- SSRF via Ollama URL; symlink escape in import dir.
- Rate-limit IP collapse behind Next proxy.
- No scheduled backups, metrics, frontend tests, MFA, email verification, breach-password check, or 2FA.
- `forgot-password` timing side-channel.
- `ResetPasswordRequest` lacks strength-validator parity.

---

## Prioritized Remediation Plan

1. **P0 (security):** SSRF allowlisting for Ollama; symlink/path confinement; global-settings authorization.
2. **P1 (security):** Forgot-password timing normalization; reset-password schema parity; rate-limit IP correctness behind proxy.
3. **P2 (functionality):** User-local date in payment creation; confirm backfill behavior; add frontend smoke tests.
4. **P3 (ops/recommendations):** Scheduled backups, observability, encryption-at-rest guidance, optional MFA/email verification.

### Concrete next steps

- Add Ollama host allowlisting/blocking private IPs.
- Resolve and verify import files under `DATA_DIR`; use `O_NOFOLLOW`.
- Gate `/import/settings` behind an owner/admin check or per-user settings.
- Normalize `forgot-password` timing.
- Add strength validator to `ResetPasswordRequest`.
- Fix client-IP extraction for the Next-proxy case (trusted `X-Real-IP` or document `TRUST_PROXY`).
- Use `user_today(me.timezone)` in `PaymentCreate` validation.
- Add Playwright smoke tests for auth + bill/payment/restore.
- Wire `infra/backup.sh` into a scheduler or document external cron.
- Add DB health to `/health`; publish metrics.
- Document encryption-at-rest and optional MFA/email-verification roadmap.