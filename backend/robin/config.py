"""Where Robin keeps its data and finds the built frontend. Every key and address is set in
Settings and kept in the database, never read from the environment."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class Env:
    # A relative ROBIN_DATA_DIR means next to the repo, not wherever uvicorn started. In the
    # container it is absolute.
    robin_data_dir: Path = (REPO_ROOT / os.environ.get("ROBIN_DATA_DIR", "data")).resolve()
    robin_static_dir: Path | None = (
        Path(os.environ["ROBIN_STATIC_DIR"]) if os.environ.get("ROBIN_STATIC_DIR") else None
    )


env = Env()
