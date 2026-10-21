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
            # The redact filter has formatted and scrubbed a traceback by now, unless there is
            # no secret yet to scrub, when it leaves the traceback unformatted.
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
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
    """Keep every line the root logger handles, and uvicorn's own, where the traceback of a
    500 is written. Uvicorn's logging config stops `uvicorn` from propagating to root, so it
    gets a ring of its own, but only then, or each line would be kept twice. Called before
    `redact.install`, which then scrubs what reaches it like every other handler."""
    server = logging.getLogger("uvicorn")
    for logger in (logging.getLogger(), *([] if server.propagate else [server])):
        if not any(isinstance(h, _Ring) for h in logger.handlers):
            logger.addHandler(_Ring())


def since(after: int) -> list[dict[str, Any]]:
    """Every kept line newer than the line `after`, oldest first."""
    return [line for line in _lines if line["id"] > after]
