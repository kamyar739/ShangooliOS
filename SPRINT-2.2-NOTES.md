# Sprint 2.2 — Marketplace Export Packages

Turn a ready listing into a portable marketplace publishing package.

## Included

- Readiness-gated ZIP export from the listing screen
- Human-readable listing copy and publish checklist
- Structured JSON manifest with listing, pricing, tags, images, and checklist data
- Listing images ordered by the standard marketplace image slots
- Packages saved in each artwork's `04 Exports` workspace folder
- Automated package-content, route, UI, and validation tests

## Verification

- `.venv/bin/python -m pytest -q`
- 52 tests passed
