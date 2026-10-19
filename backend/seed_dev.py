"""Write the keys in dev-keys.json, at the repo root, into a local database's settings.

Run it against the test container's data, with the container stopped:
    ROBIN_DATA_DIR=data/test uv run python seed_dev.py
Blank values are skipped, so a field left empty keeps what Settings has.
"""

import json

from robin import db
from robin.config import REPO_ROOT, env

keys = json.loads((REPO_ROOT / "dev-keys.json").read_text(encoding="utf-8"))
env.robin_data_dir.mkdir(parents=True, exist_ok=True)
db.init_db()
changed = db.save_settings({k: v for k, v in keys.items() if v not in ("", None)})
print(f"{env.robin_data_dir}: {', '.join(changed) or 'nothing set'}")
