"""Keep credentials out of the log stream and out of error text sent to the browser.

A backstop for the accidental case: a traceback, or a library that dumps a request.
"""

import logging

_SECRETS: set[str] = set()

# uvicorn's loggers keep handlers of their own, which the root's filter never sees.
_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def remember(*values: str) -> None:
    """Register values that must never appear in a log line."""
    for value in values:
        if value and len(value) >= 8:
            _SECRETS.add(value)


def scrub(text: str) -> str:
    """`text` with every registered secret replaced."""
    for secret in _SECRETS:
        text = text.replace(secret, "[redacted]")
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _SECRETS:
            return True
        message = record.getMessage()
        if any(secret in message for secret in _SECRETS):
            record.msg = scrub(message)
            record.args = ()
        # A traceback is formatted once and kept on the record, so it is scrubbed here before
        # any handler formats it.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def install() -> None:
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactFilter) for f in handler.filters):
                handler.addFilter(RedactFilter())
