# Variable bills — estimated amounts with confirmation

## Problem

Recurring bills with usage-based amounts (water, power) are generated at the
template amount, which is only correctable when marking paid. The user wants a
suggested amount from history, confirmed before the instance joins the bills
list.

## Decisions

- `BillTemplate.amount_varies: bool` — opt-in per bill.
- `PaymentInstance.amount_estimated: bool` — instance created from an estimate
  and not yet confirmed.
- Suggestion = **median of the last 3 confirmed amounts** for the bill
  (by due_date desc, excluding estimated rows); fallbacks: all confirmed
  history, then the template amount.
- Estimated instances are excluded from the normal payments list, overdue
  handling, reminders and stats until confirmed; they surface in a
  "needs confirmation" queue (payments page + dashboard attention).
- Confirming = PATCH the instance amount (`PATCH /bills/payments/{id}/amount`),
  which clears `amount_estimated`. Pay-with-override stays as-is.
- Backup schema gains both fields (version bump; old backups restore with
  `amount_varies=False`, `amount_estimated=False`).

## Surface

- Backend: model + Alembic revision, recurrence suggestion helper used at all
  instance-creation sites, schemas, router endpoints (queue + confirm),
  reminder/stats exclusions, backup/restore, tests.
- Frontend: bill-form toggle, payments "Needs confirmation" section with a
  dialog showing the recent amounts, dashboard attention card, i18n (en).
- Implements a new PRD FR-018 (see `context/foundation/prd.md`).

## Status

- Backend shipped: model columns + revision `c309f7a9fbf3`, median suggestion in
  recurrence (all creation sites), confirm endpoint, needs-confirmation queue,
  reminder/stats exclusions, full-payment auto-confirm, backup schema v8
  (old backups default the new flags to false), 9 new tests (583 total green).
- Frontend shipped: bill-form toggle, payments "needs confirmation" card with a
  confirm dialog showing the recent amounts, en strings.
- Dashboard attention card deferred (the queue card on Payments covers discovery
  for now).
