# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import signal
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from amcrest2mqtt.mixins.loops import LoopsMixin
from amcrest2mqtt.mixins.helpers import HelpersMixin


class FakeLooper(HelpersMixin, LoopsMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True
        self.device_interval = 1
        self.snapshot_update_interval = 1

    async def refresh_all_devices(self):
        pass

    async def collect_all_device_events(self):
        pass

    async def check_for_events(self):
        pass

    async def collect_all_device_snapshots(self):
        pass

    async def cleanup_old_recordings(self):
        pass

    async def setup_device_list(self):
        pass

    def mark_ready(self):
        pass

    def heartbeat_ready(self):
        pass


class TestDeviceLoop:
    @pytest.mark.asyncio
    async def test_calls_refresh_then_sleeps(self):
        looper = FakeLooper()
        call_count = 0

        async def mock_refresh():
            nonlocal call_count
            call_count += 1
            looper.running = False

        looper.refresh_all_devices = mock_refresh
        await looper.device_loop()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_handles_cancelled_error(self):
        looper = FakeLooper()
        looper.refresh_all_devices = AsyncMock()

        with patch("amcrest2mqtt.mixins.loops.asyncio.sleep", side_effect=asyncio.CancelledError):
            await looper.device_loop()

        looper.logger.debug.assert_called()


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_calls_heartbeat_ready(self):
        looper = FakeLooper()
        heartbeat_called = False

        def mock_heartbeat():
            nonlocal heartbeat_called
            heartbeat_called = True
            looper.running = False

        looper.heartbeat_ready = mock_heartbeat

        with patch("amcrest2mqtt.mixins.loops.asyncio.sleep", new_callable=AsyncMock):
            await looper.heartbeat()

        assert heartbeat_called

    @pytest.mark.asyncio
    async def test_handles_cancelled_error(self):
        looper = FakeLooper()

        with patch("amcrest2mqtt.mixins.loops.asyncio.sleep", side_effect=asyncio.CancelledError):
            await looper.heartbeat()

        looper.logger.debug.assert_called()


class TestMainLoop:
    @pytest.mark.asyncio
    async def test_signal_handler_registration(self):
        looper = FakeLooper()
        looper.running = False
        looper.handle_signal = MagicMock()
        looper.setup_device_list = AsyncMock()

        with (
            patch("amcrest2mqtt.mixins.loops.signal.signal") as mock_signal,
            patch("amcrest2mqtt.mixins.loops.asyncio.create_task", side_effect=lambda coro, **kw: asyncio.ensure_future(coro)),
            patch("amcrest2mqtt.mixins.loops.asyncio.gather", new_callable=AsyncMock),
        ):
            await looper.main_loop()

        # Should register handlers for SIGTERM and SIGINT
        assert mock_signal.call_count == 2
        sig_nums = [c.args[0] for c in mock_signal.call_args_list]
        assert signal.SIGTERM in sig_nums
        assert signal.SIGINT in sig_nums

    @pytest.mark.asyncio
    async def test_creates_all_tasks(self):
        looper = FakeLooper()
        looper.handle_signal = MagicMock()
        looper.setup_device_list = AsyncMock()
        created_tasks = []

        def mock_create_task(coro, **kwargs):
            created_tasks.append(kwargs.get("name", "unknown"))
            # cancel the coro immediately
            task = asyncio.ensure_future(coro)
            task.cancel()
            return task

        with (
            patch("amcrest2mqtt.mixins.loops.signal.signal"),
            patch("amcrest2mqtt.mixins.loops.asyncio.create_task", side_effect=mock_create_task),
            patch("amcrest2mqtt.mixins.loops.asyncio.gather", new_callable=AsyncMock),
        ):
            await looper.main_loop()

        assert len(created_tasks) == 6
        assert "device_loop" in created_tasks
        assert "heartbeat" in created_tasks
