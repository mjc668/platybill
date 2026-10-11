---
change_id: savings-insights
title: Savings insights — local-model recommendations on reducing bills
status: planned
created: 2026-10-11
updated: 2026-10-11
---

## Notes

A separate page (`/dashboard/insights`) that helps reduce household bills. A
deterministic layer computes the facts from existing data (annualized totals,
biggest movers, subscription creep, price trends); a local Ollama text model
then writes a short summary and prioritised suggestions — including general
tactics (annual billing, plan comparison, bundling) — grounded in those facts.
Reports are generated automatically **monthly** and cached, with an on-demand
refresh. The model receives an aggregate-only profile (no account refs, no
emails) and a configurable country hint (AU for this deployment). Shares the
Ollama client with bill-import.
