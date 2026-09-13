# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from unittest.mock import MagicMock

import pytest

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
