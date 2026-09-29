# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from amcrest2mqtt.mixins.helpers import HelpersMixin
from amcrest2mqtt.mixins.refresh import RefreshMixin


class FakeRefresher(HelpersMixin, RefreshMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True
        self.device_interval = 30
        self.devices = {}
        self.states = {}
        self.event_tasks = {}
        self.event_task_started = {}

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
    """collect_all_device_events() is a supervisor: it spawns one task per device and
    returns immediately, so each camera's stream lives and dies on its own."""

    @pytest.mark.asyncio
    async def test_spawns_one_task_per_device(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.get_events_from_device = AsyncMock()

        await r.collect_all_device_events()
        await asyncio.gather(*r.event_tasks.values())

        assert set(r.event_tasks) == {"CAM001", "CAM002"}
        assert r.get_events_from_device.call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_respawn_a_live_task(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}}
        r.states = {"CAM001": {}}
        started = asyncio.Event()

        async def _never_ends(device_id):
            started.set()
            await asyncio.sleep(3600)

        r.get_events_from_device = _never_ends

        await r.collect_all_device_events()
        await started.wait()
        first = r.event_tasks["CAM001"]

        await r.collect_all_device_events()

        assert r.event_tasks["CAM001"] is first
        await r.cancel_all_device_events()

    @pytest.mark.asyncio
    async def test_a_dead_camera_does_not_block_a_live_one(self):
        """The regression this fixes: one camera's stream ending used to leave it dead until
        every other camera's stream ended too, because they shared one asyncio.gather()."""
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        calls = []

        async def _events(device_id):
            calls.append(device_id)
            if device_id == "CAM002":
                await asyncio.sleep(3600)  # healthy sibling, streams forever

        r.get_events_from_device = _events

        await r.collect_all_device_events()
        await asyncio.sleep(0)
        await r.event_tasks["CAM001"]  # the one that dropped out

        # CAM001 has finished while CAM002 is still streaming; the cooldown has not
        # elapsed, so it is not respawned yet -- but crucially CAM002 was never disturbed.
        assert r.event_tasks["CAM001"].done()
        assert not r.event_tasks["CAM002"].done()

        r.event_task_started["CAM001"] = 0.0  # pretend the cooldown has elapsed
        await r.collect_all_device_events()
        await asyncio.sleep(0)

        assert calls.count("CAM001") == 2
        assert calls.count("CAM002") == 1
        await r.cancel_all_device_events()

    @pytest.mark.asyncio
    async def test_respawn_waits_for_the_cooldown(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}}
        r.states = {"CAM001": {}}
        r.get_events_from_device = AsyncMock()

        await r.collect_all_device_events()
        await r.event_tasks["CAM001"]
        await r.collect_all_device_events()
        await asyncio.sleep(0)

        assert r.get_events_from_device.call_count == 1

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
        await asyncio.gather(*r.event_tasks.values())

        assert set(r.event_tasks) == {"CAM001"}
        assert r.get_events_from_device.call_count == 1

    @pytest.mark.asyncio
    async def test_error_handling_per_device(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}, "CAM002": {}}
        r.states = {"CAM001": {}, "CAM002": {}}
        r.get_events_from_device = AsyncMock(side_effect=[Exception("fail"), None])
        r.get_device_name = MagicMock(return_value="Camera")

        await r.collect_all_device_events()
        await asyncio.gather(*r.event_tasks.values())

        r.logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_all_clears_live_tasks(self):
        r = FakeRefresher()
        r.devices = {"CAM001": {}}
        r.states = {"CAM001": {}}

        async def _never_ends(device_id):
            await asyncio.sleep(3600)

        r.get_events_from_device = _never_ends

        await r.collect_all_device_events()
        await asyncio.sleep(0)
        task = r.event_tasks["CAM001"]

        await r.cancel_all_device_events()

        assert task.cancelled()
        assert r.event_tasks == {}


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
