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

    def __init__(self, *, channel=None, timeout=None):
        self.logger = MagicMock()
        cfg = {}
        if channel is not None:
            cfg["snapshot_channel"] = channel
        if timeout is not None:
            cfg["snapshot_timeout"] = timeout
        self.amcrest_config = cfg
        self.calls = []

        outer = self

        class Cam:
            async def async_snapshot(self, *, channel=None, timeout=None):
                outer.calls.append({"channel": channel, "timeout": timeout})
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
