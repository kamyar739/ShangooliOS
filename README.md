# ShangooliOS — Fresh Start

This version intentionally avoids Python packaging.

## Run it

```bash
cd ~/Documents/ShangooliOS
source .venv/bin/activate
python app/main.py init-db
python app/main.py seed
python app/main.py collections
```

Expected final output:

```text
CEL: The Celebration Collection | active | target 8
DEN: Dental Collection | planned | target 20
```

## Run the web app

```bash
cd ~/Documents/ShangooliOS
.venv/bin/uvicorn web.app:app --reload
```

Open `http://127.0.0.1:8000` in a browser.

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

## Printify API setup

Create a Printify personal access token with catalog, product, upload, and shop access.
On a listing, choose **Set up with Printify API** and enter the token. ShangooliOS
retrieves the available shops and lets you select the Etsy-connected shop by name.
By default they are saved in a local `.env` file so the app can reconnect after a restart.
The file is excluded from Git and restricted to the current macOS user, but it contains the
token as plain text.

Environment variables remain available as an optional launch-time alternative:

```bash
export PRINTIFY_API_TOKEN="your-token"
export PRINTIFY_SHOP_ID="your-shop-id"
.venv/bin/uvicorn web.app:app --reload
```

Credentials are never stored in the project database or repository.
