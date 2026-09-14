# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from unittest.mock import MagicMock

import pytest

from amcrest2mqtt.mixins.amcrest_api import AmcrestAPIMixin
from amcrest2mqtt.mixins.events import EventsMixin


class FakeVision(EventsMixin):
    """Harness for _capture_and_publish_vision's fallback ordering and guards."""

    def __init__(self, *, snapshot=None, cached=None, privacy=False, vision_enabled=True):
        self.logger = MagicMock()
        self.config = {"vision_request": vision_enabled}
        self.amcrest_devices = {"cam1": {"privacy_mode": privacy}}
        self.last_event_image = {"cam1": cached} if cached else {}
        self.vision_tasks = set()
        self._snapshot = snapshot
        self.snapshot_calls = 0
        self.published = []

    def get_device_name(self, device_id):
        return device_id

    async def get_snapshot_from_device(self, device_id):
        self.snapshot_calls += 1
        return self._snapshot

    async def publish_vision_request(self, device_id, image_b64, source):
        self.published.append((device_id, image_b64, source))


class TestVisionFallback:
    @pytest.mark.asyncio
    async def test_prefers_live_snapshot(self):
        v = FakeVision(snapshot="LIVE", cached="OLD")
        await v._capture_and_publish_vision("cam1")
        assert v.published == [("cam1", "LIVE", "motion_snapshot")]

    @pytest.mark.asyncio
    async def test_falls_back_to_cached_recording_image(self):
        v = FakeVision(snapshot=None, cached="OLD")
        await v._capture_and_publish_vision("cam1")
        assert v.published == [("cam1", "OLD", "motion_last_event_image")]

    @pytest.mark.asyncio
    async def test_privacy_mode_blocks_the_cached_fallback(self):
        """The live snapshot already returns None under privacy mode; the cached image
        predates the lens being masked, so reusing it would bypass the privacy guard."""
        v = FakeVision(snapshot=None, cached="OLD", privacy=True)
        await v._capture_and_publish_vision("cam1")
        assert v.published == []

    @pytest.mark.asyncio
    async def test_does_no_camera_work_when_vision_disabled(self):
        v = FakeVision(snapshot="LIVE", cached="OLD", vision_enabled=False)
        await v._capture_and_publish_vision("cam1")
        assert v.published == []
        assert v.snapshot_calls == 0, "must not hit the camera when vision is disabled"

    @pytest.mark.asyncio
    async def test_warns_when_no_image_available(self):
        v = FakeVision(snapshot=None, cached=None)
        await v._capture_and_publish_vision("cam1")
        assert v.published == []
        v.logger.warning.assert_called_once()


class FakeSnap(AmcrestAPIMixin):
    """Harness asserting the exact snapshot request shape."""

    def __init__(self, *, channel=None, timeout=None, fail_times=0, error=None):
        self.logger = MagicMock()
        cfg = {}
        if channel is not None:
            cfg["snapshot_channel"] = channel
        if timeout is not None:
            cfg["snapshot_timeout"] = timeout
        self.amcrest_config = cfg
        self.calls = []

        outer = self
        err = error or RuntimeError("boom-500")

        class Cam:
            async def async_snapshot(self, *, channel=None, timeout=None):
                outer.calls.append({"channel": channel, "timeout": timeout})
                if len(outer.calls) <= fail_times:
                    raise err
                return b"\xff\xd8JPEG"

        self.amcrest_devices = {"cam1": {"camera": Cam(), "privacy_mode": False}}

    def get_device_name(self, device_id):
        return device_id

    def is_rebooting(self, device_id):
        return False

    def increase_api_calls(self):
        pass

    def upsert_state(self, device_id, **kwargs):
        pass

    async def publish_device_state(self, device_id):
        pass


class TestSnapshotRequestShape:
    """snapshot.cgi with NO channel returns HTTP 500 on some models while the identical
    request with an explicit channel returns 200 -- so the channel must be sent."""

    @pytest.mark.asyncio
    async def test_sends_an_explicit_channel_by_default(self):
        snap = FakeSnap()
        out = await snap.get_snapshot_from_device("cam1")
        assert out, "should return an encoded image"
        assert snap.calls == [{"channel": 1, "timeout": 25}], "channel AND timeout must reach the library"

    @pytest.mark.asyncio
    async def test_channel_is_configurable(self):
        snap = FakeSnap(channel=2)
        await snap.get_snapshot_from_device("cam1")
        assert snap.calls == [{"channel": 2, "timeout": 25}]

    @pytest.mark.asyncio
    async def test_timeout_reaches_the_library_not_just_wait_for(self):
        """python-amcrest enforces its own 6.05s httpx read timeout and raises
        CommError(ReadTimeout) before any outer asyncio.wait_for can fire, so passing the
        timeout only to wait_for silently has no effect."""
        snap = FakeSnap(timeout=30)
        await snap.get_snapshot_from_device("cam1")
        assert snap.calls[0]["timeout"] == 30


class TestSnapshotLogLevels:
    """A single failed attempt is not a failure -- measured in production, 256 attempt-1
    failures produced only 10 exhausted retries. Logging each attempt at warning buried the
    ~120/day that actually lost a snapshot under ~2,050/day that recovered on the next try."""

    @pytest.fixture(autouse=True)
    def _no_backoff(self, monkeypatch):
        """The real loop backs off 5-15s between attempts; skip the wall-clock wait."""

        async def instant(_seconds):
            return None

        monkeypatch.setattr("amcrest2mqtt.mixins.amcrest_api.asyncio.sleep", instant)

    @pytest.mark.asyncio
    async def test_recovered_attempt_is_debug_not_warning(self):
        """Attempt 1 fails, attempt 2 succeeds: the snapshot was delivered, so nothing above
        debug should be emitted."""
        snap = FakeSnap(fail_times=1)
        out = await snap.get_snapshot_from_device("cam1")

        assert out, "the retry should have produced an image"
        assert len(snap.calls) == 2
        snap.logger.warning.assert_not_called()
        snap.logger.error.assert_not_called()
        assert any("snapshot attempt 1/3 failed" in c.args[0] for c in snap.logger.debug.call_args_list)

    @pytest.mark.asyncio
    async def test_exhausted_retries_log_error_carrying_the_cause(self):
        """The give-up line is the event that matters, so it must be error-level AND name the
        underlying exception -- demoting the per-attempt lines must not lose the cause."""
        snap = FakeSnap(fail_times=99, error=RuntimeError("HTTP 500 from snapshot.cgi"))
        out = await snap.get_snapshot_from_device("cam1")

        assert out is None
        assert len(snap.calls) == 3, "should exhaust all three attempts"
        snap.logger.error.assert_called_once()
        message = snap.logger.error.call_args.args[0]
        assert "failed after 3 tries" in message
        assert "HTTP 500 from snapshot.cgi" in message, "the give-up line must carry the cause"
        snap.logger.info.assert_not_called()
