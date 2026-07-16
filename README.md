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
