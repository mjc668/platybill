---
change_id: bill-import
title: Bill import — upload, watched directory, and email-in with local Ollama extraction
status: planned
created: 2026-10-11
updated: 2026-10-11
---

## Notes

Let the app ingest a bill from three sources — a manual upload, a polled
directory (`/data/import`), or an IMAP mailbox — extract the useful fields with
a local Ollama vision/text model, and land the result as a **draft** that the
user confirms before anything is written. Matched variable bills prefill the
existing "confirm amount" queue; unmatched drafts offer a bill picker. Nothing
is ever auto-applied. Digital PDFs take the text path (pypdf → text model);
scans and photos take the vision path. See `recommended_models.md` for the
model shortlist.
