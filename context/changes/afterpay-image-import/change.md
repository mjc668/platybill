---
change_id: afterpay-image-import
title: Image-based Afterpay / BNPL instalment screenshot importer
status: in-progress
created: 2026-11-24
updated: 2026-11-24
---

## Notes

Extend the bill-import upload and watched-folder paths so screenshots of
Afterpay / BNPL instalment lists ("Your orders" / "Upcoming payments") produce
one pending `ImportDraft` per instalment row instead of a single summed draft.
See `spec.md` in this directory for full requirements and constraints.
