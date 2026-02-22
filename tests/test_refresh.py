# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import pytest
from unittest.mock import AsyncMock, MagicMock

from amcrest2mqtt.mixins.refresh import RefreshMixin
from amcrest2mqtt.mixins.helpers import HelpersMixin


class FakeRefresher(HelpersMixin, RefreshMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True
        self.device_interval = 30
        self.devices = {}
        self.states = {}

    def is_rebooting(self, device_id):
        return self.states.get(device_id, {}).get("internal", {}).get("rebooting", False)

    async def build_device_states(self, device_id):
        return True

    async def publish_device_state(self, device_id):
        pass

    async def get_events_from_device(self, device_id):
        pass

    async def get_snapshot_from_device(self, device_id):
        pass


class TestRefreshAllDevices:
    @pytest.mark.asyncio
    async def test_refreshes_all_non_rebooting_devices(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}, "CAM003": {}}
        r.states = {"CAM001": {}, "CAM002": {}, "CAM003": {}}
        r.build_device_states = AsyncMock(return_value=True)
        r.publish_device_state = AsyncMock()

        await r.refresh_all_devices()

        assert r.build_device_states.call_count == 3
        assert r.publish_device_state.call_count == 3

    @pytest.mark.asyncio
    async def test_skips_rebooting_devices(self):
        r = FakeRefresher()
        r.devices = {
            "CAM001": {"component": {"device": {"name": "Front Yard"}}},
            "CAM002": {"component": {"device": {"name": "Back Yard"}}},
        }
        r.states = {
            "CAM001": {},
            "CAM002": {"internal": {"rebooting": True}},
        }
        r.build_device_states = AsyncMock(return_value=True)
        r.publish_device_state = AsyncMock()

        await r.refresh_all_devices()

        assert r.build_device_states.call_count == 1
        r.build_device_states.assert_called_once_with("CAM001")

    @pytest.mark.asyncio
    async def test_publishes_only_changed_state(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        # CAM001 changed, CAM002 unchanged
        r.build_device_states = AsyncMock(side_effect=[True, False])
        r.publish_device_state = AsyncMock()

        await r.refresh_all_devices()

        assert r.publish_device_state.call_count == 1

    @pytest.mark.asyncio
    async def test_error_isolation_per_device(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.build_device_states = AsyncMock(side_effect=[Exception("api error"), True])
        r.publish_device_state = AsyncMock()
        r.get_device_name = MagicMock(return_value="Camera")

        await r.refresh_all_devices()

        # One should succeed even though the other failed
        r.logger.error.assert_called_once()
        assert r.publish_device_state.call_count == 1


class TestCollectAllDeviceEvents:
    @pytest.mark.asyncio
    async def test_collects_events_from_all_devices(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.get_events_from_device = AsyncMock()

        await r.collect_all_device_events()

        assert r.get_events_from_device.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_rebooting_devices(self):
        r = FakeRefresher()
        r.devices = {
            "CAM001": {"component": {"device": {"name": "Front Yard"}}},
            "CAM002": {"component": {"device": {"name": "Back Yard"}}},
        }
        r.states = {
            "CAM001": {},
            "CAM002": {"internal": {"rebooting": True}},
        }
        r.get_events_from_device = AsyncMock()

        await r.collect_all_device_events()

        assert r.get_events_from_device.call_count == 1

    @pytest.mark.asyncio
    async def test_error_handling_per_device(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.get_events_from_device = AsyncMock(side_effect=[Exception("fail"), None])
        r.get_device_name = MagicMock(return_value="Camera")

        await r.collect_all_device_events()

        r.logger.error.assert_called_once()


class TestCollectAllDeviceSnapshots:
    @pytest.mark.asyncio
    async def test_collects_snapshots_from_all_devices(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.get_snapshot_from_device = AsyncMock()

        await r.collect_all_device_snapshots()

        assert r.get_snapshot_from_device.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_rebooting_devices(self):
        r = FakeRefresher()
        r.devices = {
            "CAM001": {"component": {"device": {"name": "Front Yard"}}},
            "CAM002": {"component": {"device": {"name": "Back Yard"}}},
        }
        r.states = {
            "CAM001": {},
            "CAM002": {"internal": {"rebooting": True}},
        }
        r.get_snapshot_from_device = AsyncMock()

        await r.collect_all_device_snapshots()

        assert r.get_snapshot_from_device.call_count == 1
