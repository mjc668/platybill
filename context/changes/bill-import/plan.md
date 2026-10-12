# Bill import — implementation plan

## Frozen contract

- Three sources feed one pipeline: **upload** (multipart), **watched directory**
  (`IMPORT_DIR`, default `/data/import`), **IMAP mailbox**.
- Extraction is local-only via Ollama. Digital PDFs: `pypdf` text → text model.
  Scans/photos: render (pypdfium2) → vision model. Two-phase OCR fallback
  (`OLLAMA_OCR_MODEL` → text model) when the primary parse fails.
- Every import becomes an `ImportDraft`. **Nothing is auto-applied.** Confirm
  writes; discard drops.
- Apply rules:
  - matched to a variable bill with a queued estimated instance → prefill the
    existing confirm flow (amount PATCH clears `amount_estimated`)
  - matched to a bill with no unpaid instance for the period → create the
    instance with the extracted amount, already confirmed
  - unmatched → draft waits with a bill picker
- Dedupe: unique `source_ref` (file sha256 for directory/upload, IMAP
  message-id + attachment index for email). Re-polls never duplicate.
- Files are transient: parsed → deleted by default (`IMPORT_KEEP_FILES=false`);
  failures move to `IMPORT_DIR/failed` with a sidecar `.error` file.

## Data model (migration)

`import_drafts`:
`id, user_id FK, source(upload|directory|email), source_ref(unique), filename,
provider, amount Money, currency, due_date, period, raw_text, matched_bill_id FK
null, status(pending|confirmed|discarded|failed), error, created_at, processed_at`.

## Config (env)

| Var | Default | Notes |
| --- | --- | --- |
| `IMPORT_ENABLED` | `false` | master switch for polls; uploads allowed when Ollama configured |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | shared with savings-insights |
| `OLLAMA_MODEL` | `numind/nuextract3:q4_k_m` | primary document→JSON (GGUF; `:latest` is MLX-only) |
| `OLLAMA_OCR_MODEL` | `maternion/LightOnOCR-2:1b` | optional two-phase |
| `OLLAMA_TEXT_MODEL` | `gemma4` | digital-PDF text path + phase 2 |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | |
| `IMPORT_DIR` | `/data/import` | inside appdata by default |
| `IMPORT_POLL_MINUTES` | `15` | |
| `IMPORT_MAX_FILE_MB` | `15` | |
| `IMPORT_KEEP_FILES` | `false` | |
| `IMAP_HOST/PORT/USER/PASSWORD/FOLDER/TLS` | — / `993` / — / — / `INBOX` / `true` | password is SecretStr |
| `IMAP_POLL_MINUTES` | `15` | |
| `IMAP_MARK_READ` | `true` | mark processed messages read |
| `IMAP_ALLOWED_SENDERS` | `[]` | optional whitelist |

## Services

- `app/services/ollama.py` (shared) — `generate_json(model, prompt, images=None,
  schema=None, timeout=...)` against `/api/generate` with `format` schema,
  `temperature: 0`, `stream: false`; typed errors (`OllamaUnavailable`,
  `OllamaBadResponse`).
- `app/services/bill_extract.py` — bytes/text → `ExtractedBill` dataclass
  (`provider, amount, currency, due_date, period, confidence`). PDF text via
  pypdf; render page 1 (max 2) at 1540 px via pypdfium2; JSON-schema prompt;
  one retry via two-phase on parse failure.
- `app/services/bill_import.py` — `create_draft_from_file/text`, matching
  (normalized token overlap on provider vs bill name, currency, amount
  proximity to the current estimate), `confirm_draft`, `discard_draft`,
  `poll_directory`, `poll_email`.

## API (`app/routers/imports.py`)

- `POST /import/upload` — multipart; synchronous extract; rate-limited
  (`import_rate_limit`); returns the draft.
- `GET /import/drafts?status=pending` — review list (joins bill name).
- `PATCH /import/drafts/{id}` — edit fields / set `matched_bill_id`.
- `POST /import/drafts/{id}/confirm` — apply per contract; returns what it
  touched (`{instance_id, bill_id, created_instance}`).
- `POST /import/drafts/{id}/discard`.
- `GET /import/status` — ollama reachable + model, imap configured (masked),
  watch dir, pending count, last poll result/error.
- `POST /import/test-ollama` — tiny round-trip to verify connectivity.
- `POST /import/scan-now` — run both pollers immediately.

## Scheduler (`app/main.py` lifespan)

- `poll_import_directory` / `poll_import_email` on `IMPORT_POLL_MINUTES` /
  `IMAP_POLL_MINUTES` when `IMPORT_ENABLED` (directory) / IMAP configured.
- Startup catch-up run in the executor, like reminders.

## Frontend

- **Settings → "Bill import" tile**: Ollama status + model, IMAP configured
  (masked), watch dir, pending count (links to Payments), "Test Ollama",
  "Scan now". Env-configured values read-only; mirrors EmailNotificationsTile.
- **Payments page**: "Imported bills" review card (same pattern as the
  variable-bills card) with provider/amount/date, bill picker, Confirm /
  Discard; header "Import bill" button (file input → upload → refresh card).
- New `frontend/src/lib/imports-api.ts`; i18n under `BillImport` +
  `PaymentsPage.imported*`.

## Security / privacy

- Local Ollama only; configurable URL; files never leave the LAN by default.
- Upload validation: size cap, PDF/PNG/JPEG sniff, sanitized filenames.
- IMAP password `SecretStr`, masked in status; optional sender whitelist.
- Dedupe prevents reprocessing; drafts hold extracted fields (+ raw text for
  audit) but files are deleted unless kept.

## Dependencies

`pypdf`, `pypdfium2` (wheels, no system packages). IMAP = stdlib. Ollama =
existing httpx.

## Slices

0. `backend/scripts/test_bill_extract.py` — CLI harness (`--model`, `--text`)
   for evaluating models on real bills before wiring the UI.
1. Core: ollama client + extractor + drafts + upload + review card + confirm.
2. Directory poll + status tile + scan-now.
3. Email-in (IMAP) + dedupe + whitelist.
4. Matching polish + two-phase fallback.

## Tests

- Extractor: schema parsing, text path, render path (tiny generated PDF),
  two-phase retry — all with mocked `ollama.generate_json`.
- Pipeline: draft dedupe, matching scores, confirm applies to variable queue /
  creates instance / unmatched, discard; directory poll with tmp dir; IMAP
  parsing with a fixture `.eml`; upload endpoint validation (size/type/scope).
- No Ollama in CI; everything mocked.

## Demo

Generate a synthetic bill image, upload it through the running container with
the local Ollama (`gemma4` today, NuExtract3 once pulled), and show the draft →
confirm flow. Real bills to be tested by the maintainer.

## Status

- Slices 1 (upload/drafts/review/confirm) and 2 (directory poll) shipped on the
  `ai` branch with 18 backend tests; email-in (slice 3) implemented but not yet
  exercised against a live mailbox.
- First-user feedback drove a rework: the separate "needs an amount" queue card
  and "imported bills" card are now one **ReviewInbox** on Payments with inline
  amount/date editing, a bill picker that can create the bill from the import,
  and a "Added to <month> · View" result banner. The estimate and import rows
  now resolve each other (same period → one action).
- Bug found during testing: an import creates the period's instance with the
  document's due date, and the month sync (keyed on due date) added the
  scheduled occurrence beside it — "adds it twice". Fixed with period-level
  idempotency for non-weekly templates in all recurrence creation paths
  (`_period_has_instance`), with regression tests.
- Remaining: email-in live test, dashboard nudge, currency field in the
  create-bill mini-form.
