# Printify API Integration

ShangooliOS can create an unpublished Printify product directly from a ready listing.

## Workflow

1. Choose a poster blueprint from the live Printify catalog.
2. Choose a print provider.
3. Select variants, retail prices, and the matching ShangooliOS ratio file.
4. ShangooliOS uploads each required file once.
5. ShangooliOS creates the Printify product and records its returned ID.
6. Review the draft in Printify before connecting or publishing it.
7. Use the separate confirmed publish action to send the reviewed product to Etsy.
8. Complete the final Etsy review and record the Etsy URL in ShangooliOS.

## Security

- The setup page accepts the token, retrieves the account's shops, and lets the user
  select the Etsy-connected shop by name.
- The selected token and shop ID are saved to `.env` by default.
- `.env` is excluded from Git and written with owner-only permissions, but remains plain text.
- The user can uncheck the remember option to keep credentials only in process memory.
- `PRINTIFY_API_TOKEN` and `PRINTIFY_SHOP_ID` remain an optional environment-based alternative.
- Credentials are not written to SQLite, logs, exports, or Git.
- The personal access token needs shop, catalog, product, and upload permissions.

## Verification

- `.venv/bin/python -m pytest -q`
- API calls are covered with a fake Printify client; a live creation test requires credentials.
