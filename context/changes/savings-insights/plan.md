# Savings insights — implementation plan

## Decisions (frozen)

- **Separate page** `/dashboard/insights` (not a dashboard card). The dashboard
  gets one small link/card pointing to it.
- **Auto-generate monthly** (scheduler job on the 1st, 06:00 UTC) + an
  on-demand "Refresh suggestions" button. Reports cached in the DB; UI marks
  them stale after 30 days.
- **More general advice allowed**: suggestions may include general tactics
  (annual billing discounts, plan comparison, bundling, subscription review),
  but must not invent providers or amounts. Deterministic facts are injected
  and the prompt requires every number to come from them.
- **Country hint**: `INSIGHTS_COUNTRY` (default `AU` for this deployment),
  included in the prompt so advice is locally relevant.
- **Separate change folder**; shares `app/services/ollama.py` with bill-import.

## Layers

### Deterministic facts (always rendered, no AI)

Computed per user (reuse `app/services/stats.py` patterns):
- annualized total per bill and per category (primary currency)
- top 3 categories by spend
- biggest movers: last 3 months vs previous 3, per bill (`trend_pct`)
- subscription creep: count + total of small recurring bills per category
- price trend: a bill's confirmed amounts trending up over the last 3 periods
- duplicate-looking bills (similar name/category/amount)

### AI layer (Ollama text model)

- Input JSON (aggregate only): `{country, currency, months, bills:[{name,
  category, frequency, median_amount, trend_pct, annualized}], categories:[...],
  totals:{monthly_avg, annualized}}`
- Prompt: "Use ONLY these figures for any amounts. You may add general
  money-saving tactics. Output JSON matching the schema. Never name companies
  unless they appear in the bill names."
- Output schema:
  `{summary: string, suggestions: [{title, rationale,
  estimated_saving_per_year: number|null, effort: low|medium|high,
  related_bills: [string]}]}`
- Model: `INSIGHTS_MODEL` (defaults to `OLLAMA_TEXT_MODEL`, e.g. `gemma4`).
  Text-only; no vision needed.

## Data model (migration)

`insight_reports`:
`id, user_id FK, generated_at UTCDateTime, model, payload JSON (facts +
suggestions), status(ok|error), error`.

Keep the newest report per user; the monthly job overwrites (or inserts and
prunes older rows).

## Config

| Var | Default | Notes |
| --- | --- | --- |
| `INSIGHTS_ENABLED` | `true` when `OLLAMA_BASE_URL` set | monthly job gate |
| `INSIGHTS_MODEL` | `OLLAMA_TEXT_MODEL` | |
| `INSIGHTS_COUNTRY` | `AU` | prompt hint |
| `INSIGHTS_STALE_DAYS` | `30` | UI "stale" badge |
| `OLLAMA_BASE_URL` / `OLLAMA_TIMEOUT_SECONDS` | shared | |

## API

- `GET /insights` — cached report + deterministic facts; 404-free: returns
  `{facts, report: null}` when never generated.
- `POST /insights/refresh` — regenerate now (rate-limited per user); returns
  the new report.
- `GET /insights/status` — Ollama configured/reachable, model, generated_at.

## Scheduler

- Monthly job (1st, 06:00 UTC): regenerate for every user with at least one
  non-archived bill; skip quietly when Ollama is unconfigured.
- Failure is recorded on the report row (`status=error`) and surfaced on the
  page; deterministic facts still render.

## Frontend

- New page `frontend/src/app/dashboard/insights/page.tsx`:
  - header + "Refresh suggestions" (spinner, disabled while running)
  - facts section: annualized total, top categories, biggest movers (bar-ish
    rows), subscription creep, price trends
  - suggestions section: cards with title, rationale, estimated saving,
    effort badge, related bills; **"AI-generated — verify before acting"**
    disclaimer + model + generated-at/stale badge
  - empty state: "Not generated yet — refresh" ; Ollama-unconfigured note
- Dashboard: small link card ("Ways to reduce your bills →").
- `frontend/src/lib/insights-api.ts` + i18n under `InsightsPage`.

## Security / privacy

- Aggregate-only payload; no emails, no account refs, no raw documents.
- Local Ollama only; no external calls.

## Slices

1. Facts aggregation + `GET /insights` + page rendering deterministic section.
2. Ollama narration + refresh endpoint + suggestions UI + caching table.
3. Monthly job + dashboard link + stale badge + status/error handling.

## Tests

- Facts aggregation (fixture users/bills with known totals and trends).
- Prompt builder: contains only aggregate fields; country hint present.
- Schema parsing of model output (mocked), malformed output → `status=error`
  with facts still returned.
- Monthly job: runs per user, skips when unconfigured, overwrites old report.
- Endpoint tests: empty state, cached state, refresh rate limit.

## Effort

~2 days total; slice 1 alone is ~0.5 day and useful without any model.
