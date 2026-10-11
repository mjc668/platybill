---
project: bill-tracker
version: 1
status: draft
created: 2026-06-11
context_type: greenfield
product_type: web-app
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 7
  hard_deadline: null
  after_hours_only: true
---

# Platybill — Product Requirements Document

## Vision & Problem Statement

Managing household bills and recurring payments in a spreadsheet is tedious and
error-prone. The pain combines three compounding problems: too many manual steps
(updating the sheet each month, creating next-month rows by hand), missing capability (no
reminders, no automation, no shared real-time view), and coordination overhead — family
members cannot see or update the same payment list without emailing the file back and
forth.

The insight: existing tools (YNAB, Mint, and similar) are subscription-based and
over-engineered for simple household bill tracking. They also depend on third-party cloud
services, offering no path to self-hosted or offline operation. A personal-first bill
tracker that works identically whether hosted in the cloud or on a home server — with no
third-party subscription, no data sharing with outside services, and no unnecessary
complexity — does not exist as an off-the-shelf product.

## User & Persona

**Primary persona:** A household finance manager — typically the one person (or couple)
responsible for tracking all recurring household bills. This person currently maintains
bills in a spreadsheet, manually updates it each month, and relies on their own memory for
reminders. They want a web app that replaces the spreadsheet with automation, while keeping
data under their control (either self-hosted or privately cloud-hosted).

**Secondary persona:** Other family members who each have their own account. Each account
has a fully isolated view — their own bill templates and payment instances, separate from
every other account on the same deployment.

## Success Criteria

### Primary

The core bill-tracking loop works end-to-end:

Given a user has created a bill template (e.g., "Electricity — due 15th, monthly, €120"),
when they mark this month's payment instance as paid (accepting the default amount of €120
or overriding with the actual amount paid), then the system automatically generates next
month's instance and it appears on the dashboard — with no manual intervention required.

Validated in local self-hosted deployment.

### Secondary

The system sends email reminders for payments that are upcoming or overdue, so the
household finance manager does not need to check the dashboard proactively.

### Guardrails

1. **No data loss.** Payment history is never silently corrupted or deleted. Exports and
   backups produce accurate, complete data at any point in time.
2. **Auth secure.** No unauthenticated access to any finance data.

## User Stories

### US-01: Core bill-tracking loop

- **Given** I have created a bill template (e.g., "Electricity — due 15th, monthly, €120")
- **When** I mark this month's payment instance as paid, accepting the default amount of
  €120 or overriding it with the actual amount paid
- **Then** the system automatically generates next month's instance and it appears on the
  dashboard — and the current instance's status changes to "paid" — with no manual action
  required

## Functional Requirements

### Authentication

- FR-001: User can register with email and password. Priority: must-have
  > Socratic: No counter-argument — registration is essential for family access; no simpler
  > onboarding path meets the multi-user requirement.

- FR-002: User can log in with email and password. Priority: must-have
  > Socratic: No counter-argument — authentication is foundational; cannot be deferred.

### Bill Templates

- FR-003: User can create a bill template with name, amount, currency, category, due day of month,
  recurrence type and interval, and paused flag. Priority: must-have
  > Recurrence is a unit (weekly / monthly / yearly / one-off) plus an interval count
  > ("every N" — weeks 1–4, months 1–12, years 1–5). Weekly bills anchor on a
  > first-payment date and can produce several instances per month.
  > Currency is a per-template string (PLN / EUR / USD / custom); default is PLN.
  > Socratic: Category kept as must-have — needed for export reporting and filtering.

- FR-004: User can edit an existing bill template. Priority: must-have
  > Socratic: No counter-argument — template values (amount, due day) change over time.

- FR-005: User can archive a bill template (hidden from active view; existing payment
  history preserved). Priority: must-have
  > Socratic: Archive preferred over hard delete — prevents accidental financial history
  > loss. Archived templates' instances remain accessible via export.

### Payment Instances

- FR-006: System auto-generates a payment instance from a template for the current period;
  generation is idempotent (requesting the same instance twice produces one record).
  Priority: must-have
  > Socratic: No counter-argument — idempotent generation prevents duplicate records at
  > month boundaries.

- FR-007: User can view a unified payment list sorted by due date with status indicators
  (upcoming / overdue / paid). Priority: must-have
  > Socratic: Unified list chosen over separate upcoming/overdue views — simpler to build;
  > status indicators make overdue items visible. Separate filtered views deferred to v2.

- FR-008: User can mark a payment instance as paid; the recorded amount defaults to the
  template amount with an option to override before confirming. Priority: must-have
  > Socratic: Defaulting to template amount reduces friction for the common case where
  > actual equals expected; override is available for variable bills (e.g., utilities).

- FR-019: A bill can be imported from an upload, a watched folder, or a mailbox. A local
  model extracts provider/amount/due date, and the user confirms the draft before anything
  is written; matched variable bills prefill the confirmation queue. Priority: must-have
  > Socratic: Manual entry is the main friction for usage-based bills. Local extraction
  > keeps documents on the LAN, and confirm-first protects the ledger from model mistakes.

- FR-018: A bill can be flagged "amount varies each period" (utilities). Instances for
  such bills are generated with a suggested amount — the median of the last three
  confirmed amounts — and stay out of the payments list, reminders and stats until the
  user confirms the real amount. Paying an instance in full also settles its estimate.
  Priority: must-have
  > Socratic: Usage-based bills have no fixed amount; silently reusing the template
  > amount makes the list lie. A confirm step keeps the schedule honest without manual
  > per-period entry, and the median (not the mean) resists one outlier month.

- FR-009: System auto-creates the next-period payment instance when the current one is
  marked as paid; auto-creation is suppressed when the template's paused flag is set.
  Priority: must-have
  > Socratic: Pause flag at template level allows stopping recurrence without deleting the
  > template or losing its payment history.

- FR-021: User can delete a payment instance with a confirmation dialog. Deletion is
  permanent from the user's perspective but implemented as a soft-delete (`is_deleted`
  flag) so the row acts as a tombstone and the seeder never regenerates the entry.
  Only the selected instance is affected — the bill template and all other instances
  are untouched. Priority: must-have
  > Hard-delete + regeneration-prevention via template-level flags was attempted and
  > rejected: it coupled instance lifecycle to template state and required a "reactivate"
  > concept that had no natural UX home. Soft-delete on the instance is the correct
  > abstraction — the idempotency check in ensure_current_period_instances already
  > skips periods where any row (including soft-deleted) exists.

- FR-019: User can revert an accidentally marked-as-paid payment instance back to its
  natural unpaid state (upcoming or overdue) without a confirmation dialog. Priority: must-have
  > Reverting clears paid_at and paid_amount; status is recomputed dynamically (overdue if
  > due_date < today, otherwise upcoming). The auto-generated next-period instance created
  > by the original mark-paid action is preserved to avoid cascading data loss. Action is
  > trivially reversible (user can mark paid again), so no confirmation gate is needed.

- FR-020: Bill templates and payment instances are owned by the user who created them.
  User A cannot read, modify, or delete User B's templates or payment instances.
  All API endpoints that return or mutate bill or payment data must filter by the
  authenticated user's ID. Priority: must-have (security — blocking)
  > This is enforced at the data layer (`BillTemplate.user_id` FK), not at the router
  > level alone. PaymentInstance inherits user scope transitively through its
  > `bill_id → BillTemplate.user_id` FK; no direct `user_id` column is needed on
  > `PaymentInstance`. Every query on bill or payment data must join or filter through
  > `BillTemplate.user_id = current_user.id`.

### Export & Backup

- FR-010: User can export their own payment data to a spreadsheet file (.xlsx). The export
  is scoped to the authenticated user's templates and instances only. Priority: must-have
  > Socratic: Both export and backup are must-have — spreadsheet export serves family
  > review; data backup enables portability between deployment modes.

- FR-011: User can download a full data backup of their own data in a portable
  machine-readable format. The backup is scoped to the authenticated user's templates and
  instances only. Priority: must-have
  > Socratic: Backup and spreadsheet export serve distinct purposes; both justified for v1.

### Reminders

- FR-012: System sends email reminders for upcoming and overdue payments.
  Priority: nice-to-have
  > Scoped to email-only delivery — browser push notifications deferred due to
  > implementation complexity. Email works in both deployment modes with appropriate mail
  > provider configuration.
  > Reminder send time is configurable per user in 30-minute increments (00:00–23:30,
  > stored as minutes since midnight). The scheduler fires every 30 minutes and matches
  > users whose configured time equals the current UTC time. Server time (UTC) is shown
  > in the settings UI so users can account for the timezone offset.

- FR-022: Each payment row displays an email notification indicator (@ icon): gray when
  no reminder has been sent for that instance, amber when at least one reminder was sent.
  Clicking the icon shows the timestamp of the most recent send. Priority: nice-to-have
  > Implemented via `email_sent_at` (timestamptz, nullable) on `PaymentInstance` — stamped
  > on every successful reminder send. Exposed in `PaymentInstanceOut` and rendered in the
  > frontend without a separate API call.

### PWA

- FR-013: App is installable as a PWA on mobile and desktop.
  Priority: must-have
  > Local operators are expected to configure HTTPS; guidance deferred to deployment docs.

### Localisation

- FR-016: The UI ships in English only for the Platybill launch; the language switcher and
  the Polish/German translations are stripped for now. Priority: could-have (deferred)
  > Socratic: The 3.1.x line shipped en/pl/de; keeping one locale during the SQLite +
  > rebrand relaunch cuts surface area. Backend reminder emails still carry en/pl/de
  > templates and honor the stored per-account language preference, so existing accounts
  > keep receiving emails in their language.

- FR-017: (deferred with FR-016) The UI language switcher and per-account locale
  persistence return when translations are reintroduced.

## Non-Functional Requirements

- **Data persistence:** All payment data is retained durably. The user's payment history
  survives app restarts and redeployments without data loss.

- **Mobile usability:** The app layout is fully operable on screens as narrow as 375px
  without requiring pinch-zoom. Family members check bills on phones; the primary view
  must work on a standard mobile screen.

## Business Logic

Platybill automatically derives the status of each payment and creates the next recurring
instance without user intervention: given a bill's due date and whether it has been marked
paid, the system classifies the instance as upcoming, overdue, or paid — and when a
recurring instance is marked paid, the system produces the next period's instance from the
bill's recurrence schedule, without any additional user action.

Two distinct rules compose this behavior:

1. **Status classification:** Given today's date, a payment instance's due date, and
   whether it has been marked paid, the system assigns one of three statuses: `upcoming`
   (due date is in the future and unpaid), `overdue` (due date has passed and unpaid), or
   `paid`. This classification drives the dashboard display and email reminder triggers.

2. **Recurrence automation:** Given a bill template's recurrence schedule (its frequency
   and scheduled due day within the month) and a payment instance that has been marked
   paid, the system derives the next period's due date and creates a new instance for that
   period — unless the template's paused flag is set. The output is a new payment instance
   ready to appear on the dashboard with `upcoming` status. Auto-creation does not occur
   for one-time (non-recurring) bills or for templates with the paused flag set.

## Access Control

All users authenticate before accessing any finance data.

Authentication method: email and password.

Role model: per-user isolation. Each authenticated user owns their own bill templates and
payment instances. User A cannot see, edit, or delete User B's data. There are no
shared views, no cross-account reads, and no admin override path in the application
layer. Isolation is enforced at the data layer via `BillTemplate.user_id` — see FR-020.

Self-registration is supported so family members can join without requiring an invitation
from another user. Registration is intentionally open to anyone who knows the app's URL —
appropriate for a privately deployed household tool where URL distribution is controlled
by the household. Each registrant gets a fully isolated data partition.

## Non-Goals

- **No budgeting or savings goals.** Platybill tracks bills and payments only; it does
  not advise on budget allocation, savings targets, or financial planning.

- **No bank or card integrations.** No automatic transaction import of any kind (no open
  banking, no statement parsing). All data is entered manually by the user.

- **No multi-household or SaaS mode.** One household per deployment instance. No public
  sign-up, no per-user billing. Within a deployment, each user account is data-isolated
  (FR-020) — this is a security property, not a SaaS feature. Personal-first, not
  platform-first.

- **No native mobile app.** PWA is the mobile story. No app store distribution, no
  platform-specific build.

## Open Questions

1. **Local-mode PWA and HTTPS.** A self-hosted deployment without HTTPS cannot install
   as a PWA on most browsers. A reverse-proxy or certificate setup guide is needed in
   deployment documentation. — Owner: implementation team. Block: no (does not affect core
   functionality; deferred to deployment docs).

2. **Email delivery configuration (FR-012).** The mail provider, credentials, and
   configuration format for email reminders are deployment concerns, not product concerns.
   These must be documented in deployment guides. — Owner: implementation team. Block: no
   (FR-012 is nice-to-have; deferred to deployment docs).
