# Sprint 2.4 — Basic Etsy Validation

Catch essential Etsy listing problems before export or publication.

## Included

- Maximum 140-character title
- Maximum 13 tags per listing
- Maximum 20 characters per tag
- Required description and positive price
- Existing listing-image readiness requirement
- Actionable validation messages in the readiness checklist
- Validation gates shared by export and publication workflows
- Automated validation tests

## Verification

- `.venv/bin/python -m pytest -q`
- 62 tests passed

Limits verified against Etsy's official seller documentation in July 2026.
