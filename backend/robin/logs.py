"""What Robin logged lately, kept in memory for the Logs page.

Only the last `KEEP` lines, and none from before the last start: the container's own log
holds everything.
"""

from __future__ import annotations

import itertools
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

KEEP = 5000

_lines: deque[dict[str, Any]] = deque(maxlen=KEEP)
_ids = itertools.count(1)


class _Ring(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            # The redact filter has formatted and scrubbed a traceback by now.
            if record.exc_text:
                message = f"{message}\n{record.exc_text}"
            _lines.append(
                {
                    "id": next(_ids),
                    "at": datetime.fromtimestamp(record.created, UTC).isoformat(),
                    "level": record.levelname.lower(),
                    "source": record.name,
                    "message": message,
                }
            )
        except Exception:  # noqa: BLE001
            self.handleError(record)


def install() -> None:
    """Keep every line the root logger handles. Called before `redact.install`, which then
    scrubs what reaches it like every other handler."""
    root = logging.getLogger()
    if not any(isinstance(h, _Ring) for h in root.handlers):
        root.addHandler(_Ring())


def since(after: int) -> list[dict[str, Any]]:
    """Every kept line newer than the line `after`, oldest first."""
    return [line for line in _lines if line["id"] > after]
