import logging
import sys

from robin import redact


def test_secret_is_scrubbed_from_a_log_line() -> None:
    redact.remember("hunter2-hunter2-hunter2")
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling Prowlarr with token %s",
        args=("hunter2-hunter2-hunter2",),
        exc_info=None,
    )
    assert redact.RedactFilter().filter(record) is True
    assert "hunter2" not in record.getMessage()
    assert "[redacted]" in record.getMessage()


def test_short_values_are_not_registered() -> None:
    redact.remember("abc")
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="abc",
        args=None,
        exc_info=None,
    )
    redact.RedactFilter().filter(record)
    assert record.getMessage() == "abc"


def test_a_secret_in_a_traceback_is_scrubbed() -> None:
    redact.remember("tk_secret_in_traceback")
    try:
        raise RuntimeError("upstream refused tk_secret_in_traceback")
    except RuntimeError:
        record = logging.LogRecord(
            name="t",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=None,
            exc_info=sys.exc_info(),
        )
    redact.RedactFilter().filter(record)
    formatted = logging.Formatter().format(record)
    assert "tk_secret_in_traceback" not in formatted
    assert "[redacted]" in formatted


def test_uvicorns_own_handlers_are_filtered_too() -> None:
    handler = logging.StreamHandler()
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(handler)
    try:
        redact.install()
        assert any(isinstance(f, redact.RedactFilter) for f in handler.filters)
    finally:
        logger.removeHandler(handler)


def test_an_error_sent_to_the_browser_is_scrubbed() -> None:
    redact.remember("eyJ-a-tmdb-token-value")
    assert redact.scrub("TMDB said no to eyJ-a-tmdb-token-value") == "TMDB said no to [redacted]"
