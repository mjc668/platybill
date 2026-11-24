# Spec — image-based Afterpay import (BNPL instalment screenshots)

**Status:** spec only, nothing implemented.
**Context:** Platybill (this repo). Follow the repo conventions in `context/changes/` for
where a change document belongs; place this under
`context/changes/afterpay-image-import/` when you pick it up.

---

## The problem, observed against the live instance

The Bill-import **upload** path assumes **one bill per document**. Uploading a screenshot of
the Afterpay "Your orders" list produced one nonsense draft:

- provider: `"multiple orders"`
- amount: `292.84` — the **sum** of the seven instalments on that screen
  (17.76 + 31.57 + 28.50 + 64.58 + 75.00 + 43.87 + 31.56)
- due_date: **null**

That draft was discarded, not confirmed. Uploading the other five screenshots would do the
same thing, so they were not sent.

**The email path already solves this**, and that is the model to copy:

- `backend/app/services/bill_import.py:466` — BNPL extraction runs only when
  `not had_attachment and app_settings.imap_afterpay_enabled(db)`
- `is_afterpay_email(sender, subject, combined_text)` gates it
- `parse_afterpay(html_body or "", text_body or "")` (in
  `backend/app/services/afterpay_parser.py`) returns per-instalment rows
- one draft per instalment, provider `f"Afterpay: {bnpl.merchant}"`,
  source_ref `f"email:{message_id}:afterpay"`

Screenshots get none of that: they fall through to the generic single-bill vision extraction.

## Goal

An **uploaded image** of an Afterpay / BNPL instalment list produces **N drafts, one per
instalment**, each with its own merchant, amount and due date — never one summed draft.

## Requirements

1. **Detect the document shape, not the filename.** If vision extraction returns a list of
   instalments (merchant + amount + due date, with an "n of 4" style counter), treat it as a
   BNPL list. Otherwise keep the existing single-bill behaviour untouched.
2. **One draft per row.** Never aggregate. Provider naming must match the existing convention
   (`Afterpay: <merchant>`) so the current matcher can line rows up with templates such as
   `Afterpay: Target` and `Afterpay: MARULAN IGA PLUS LIQ`.
3. **Unique source_ref per row** — e.g. `upload:{file_hash}:afterpay:{row_index}`. The
   existing unique constraint is global across pending/confirmed/discarded/failed, so a
   re-upload must not create a second copy of the same instalment, and must not be silently
   suppressed when the row index shifts because the screenshot covers a different window.
4. **Deduplicate against reality, not just against drafts.** The same instalment appears on
   several screenshots as the "n of 4" counter advances and the date window rolls. Match on
   merchant + amount + due_date against existing drafts and existing payment instances before
   creating anything.
5. **Parse the date formats actually present:** `Sun, 27 Dec`, `3 Jan, 2027` (year only when
   it rolls over into the next one). Amounts are AUD with a decimal point.
6. **Carry the instalment counter** (`n of 4`) into the draft `meta` so the UI can show it and
   a later pass can reason about remaining payments.
7. **Unknown merchants create nothing.** An unmatched row stays a pending draft; do not
   auto-create bill templates from a screenshot.

## Explicit constraints

- **No auto-confirm.** Drafts land `pending` and a human confirms — same as today's upload path.
- **Do not touch the email path's behaviour.** It works; this is additive.
- **Do not change the viewport meta, manifest, or anything outside this feature.**

## Dependency

Per-instalment *matching* is fixed on `fix/import-instalment-match`
(`e507569 fix(import): prefer exact due_date match in _target_instance`), which is **not yet
merged**. Branch off that if it is still open, or off `main` with a note that the matching fix
must land for confirm to put instalments in the right slots.

## Tests

- Unit: the parser against each of the six screenshots already provided (merchant, amount,
  due date, instalment counter).
- Unit: a re-upload of the same screenshot creates no new drafts.
- Unit: a screenshot that overlaps an earlier one creates only the genuinely new instalments.
- E2E: upload a screenshot → exactly N pending drafts, no summed draft, no confirmations.

## Deliverable

Failing test first, then the implementation, full suite green, committed on a branch, pushed,
CI green. **Do not deploy, do not touch production data, do not mint or use credentials.**
Final message: what changed, test results, and anything you found that this spec did not
anticipate.
