"""Every category the backend knows is typed in the frontend, so Settings and setup do not
compile without its source panel and the line saying what is missing while it is unset."""

import re
import typing
from pathlib import Path

from robin import db

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"


def test_every_category_is_typed_in_the_frontend() -> None:
    declared = re.search(
        r"^export type Category = (.+)$", API_TS.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert declared, "lib/api.ts declares Category on one line"
    assert set(re.findall(r"'(\w+)'", declared.group(1))) == set(typing.get_args(db.Category))
