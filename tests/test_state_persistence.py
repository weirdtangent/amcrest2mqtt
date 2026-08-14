# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
"""Tests for atomic state persistence and saving on shutdown.

Two defects lived here. save_state() opened the target with O_TRUNC and then called os.fchmod,
which raises EPERM on volumes that do not permit chmod — the truncate had already happened, so a
failure left a 0-byte .dat. And save_state() was only reached from __aexit__, which the 5s
force-exit in the signal handler reliably beat, so the file silently went stale for months while
still restoring cleanly.
"""

import json
import os
import signal
import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from amcrest2mqtt.base import Base
from amcrest2mqtt.mixins.helpers import HelpersMixin


class FakeService(HelpersMixin, Base):
    def __init__(self, config_path):
        self.config = {"config_path": str(config_path)}
        self.logger = MagicMock()
        self.api_calls = 42
        self.last_call_date = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        self.running = True


@pytest.fixture
def svc(tmp_path):
    return FakeService(tmp_path)


def _dat(tmp_path):
    return tmp_path / "amcrest2mqtt.dat"


class TestSaveState:
    def test_writes_readable_state(self, svc, tmp_path):
        svc.save_state()

        assert json.loads(_dat(tmp_path).read_text())["api_calls"] == 42

    def test_leaves_no_temp_file_behind(self, svc, tmp_path):
        svc.save_state()

        # assert on the whole directory rather than glob("*.tmp"): pathlib glob does match
        # dotfiles (the stdlib glob module does not), but relying on that is a trap
        assert [q.name for q in tmp_path.iterdir()] == ["amcrest2mqtt.dat"]

    def test_a_failed_save_does_not_destroy_existing_state(self, svc, tmp_path, monkeypatch):
        svc.save_state()
        original = _dat(tmp_path).read_text()
        assert original.strip()

        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted")))
        svc.api_calls = 99
        svc.save_state()

        assert _dat(tmp_path).read_text() == original
        svc.logger.error.assert_called_once()

    def test_does_not_chmod_an_existing_file(self, svc, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(os, "fchmod", lambda *a, **k: called.append(a))

        svc.save_state()
        svc.save_state()

        assert called == []

    def test_does_not_leak_the_descriptor_when_fdopen_fails(self, svc, tmp_path, monkeypatch):
        """mkstemp hands back a raw fd; os.fdopen only takes ownership once it succeeds."""
        closed = []
        real_close = os.close
        monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError(24, "EMFILE")))

        svc.save_state()

        assert closed, "descriptor from mkstemp was never closed"
        assert [q.name for q in tmp_path.iterdir()] == []


class TestSaveOnSignal:
    def test_signal_handler_persists_state(self, svc, tmp_path, monkeypatch):
        """__aexit__ never won the race against the 5s force-exit, so the save happens here."""
        monkeypatch.setattr(threading, "Timer", lambda *a, **k: MagicMock())

        svc.handle_signal(signal.SIGTERM, None)

        assert json.loads(_dat(tmp_path).read_text())["api_calls"] == 42
        assert svc.running is False

    def test_a_failing_save_does_not_abort_shutdown(self, svc, monkeypatch):
        monkeypatch.setattr(threading, "Timer", lambda *a, **k: MagicMock())
        monkeypatch.setattr(FakeService, "save_state", lambda self: (_ for _ in ()).throw(OSError("nope")))

        svc.handle_signal(signal.SIGTERM, None)

        assert svc.running is False
        svc.logger.warning.assert_called()

    def test_a_failing_close_does_not_mask_the_fdopen_error(self, svc, tmp_path, monkeypatch):
        """The caller logs whatever propagates, so a close failure must not hide the real cause."""
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError(24, "EMFILE the real cause")))
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError(9, "EBADF noise")))

        svc.save_state()

        logged = repr(svc.logger.error.call_args)
        assert "EMFILE the real cause" in logged
        assert "EBADF noise" not in logged


class TestTempFileSafety:
    """A predictable temp path is unsafe: O_TRUNC on it inherits a stale file's permissions and
    follows a symlink to truncate whatever it points at. mkstemp avoids both."""

    def test_does_not_follow_a_symlink_at_the_predictable_temp_path(self, svc, tmp_path):
        canary = tmp_path / "canary.txt"
        canary.write_text("must survive")
        (tmp_path / "amcrest2mqtt.dat.tmp").symlink_to(canary)

        svc.save_state()

        assert canary.read_text() == "must survive"

    def test_does_not_inherit_a_stale_temp_files_permissions(self, svc, tmp_path, monkeypatch):
        stale = tmp_path / "amcrest2mqtt.dat.tmp"
        stale.write_text("junk")
        stale.chmod(0o644)

        captured = {}
        real_replace = os.replace

        def spy(src, dst):
            captured["mode"] = os.stat(src).st_mode & 0o777
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        svc.save_state()

        assert captured["mode"] == 0o600

    def test_each_save_uses_a_fresh_temp_path(self, svc, tmp_path, monkeypatch):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(str(src))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        svc.save_state()
        svc.save_state()

        assert len(set(seen)) == 2
