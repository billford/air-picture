import smtplib
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import config  # noqa: E402  pylint: disable=wrong-import-position


class _NetworkBlocked(RuntimeError):
    pass


def _refuse(*_args, **_kwargs):
    raise _NetworkBlocked("tests must not touch the network; mock it")


@pytest.fixture(autouse=True)
def _no_real_delivery(monkeypatch, tmp_path):
    """Stop the suite from delivering anything for real.

    config reads the real .env, so once email was configured, every deliver()
    test emailed the actual report to the owner. Blank the email settings and
    make real SMTP/HTTP connections raise. Tests that need them patch over
    these with their own mocks, which take precedence.
    """
    # Same for the database: a query a test forgot to mock read the real
    # air_picture.db. Tests that want a database set their own DB_PATH.
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    for key in ("EMAIL_TO", "EMAIL_FROM", "SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        monkeypatch.setattr(config, key, "")
    monkeypatch.setattr(smtplib, "SMTP", _refuse)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _refuse)
    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
