import logging

import pytest

from robin import logs, redact


def test_a_500_from_uvicorn_reaches_the_logs_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uvicorn stops its loggers at `uvicorn`, which is where an unhandled error is written."""
    server = logging.getLogger("uvicorn")
    monkeypatch.setattr(server, "propagate", False)
    monkeypatch.setattr(server, "handlers", [])
    logs.install()
    redact.install()

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")

    line = logs.since(0)[-1]
    assert line["source"] == "uvicorn.error"
    assert "RuntimeError: boom" in line["message"]
