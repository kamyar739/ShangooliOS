# Sprint 2.1 — Listings

Implemented a simple listing workflow tied to each artwork.

## Included

- Listings database table with automatic migration for existing databases
- Create a listing from an artwork
- Prefill title, description, and tags from generated Etsy listing content
- Edit marketplace, product, title, description, tags, price, and status
- View all listings from the main navigation
- View listings on each artwork page
- Delete a listing
- Price and status validation
- Automated CRUD and route tests
- Declared the HTTP test-client dependency required by the pinned web stack

## Verification

- `python -m pytest -q`
- 48 tests passed
- Dashboard and Listings pages returned HTTP 200 in a local Uvicorn smoke test
