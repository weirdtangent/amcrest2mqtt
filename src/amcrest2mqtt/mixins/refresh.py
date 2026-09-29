# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


# How long to wait before respawning a device's event-stream task after the previous one
# finished. Long enough that a hard-down camera does not spam a give-up line every 20s,
# short enough that a real reconnect is not noticeably delayed.
EVENT_STREAM_RESPAWN_COOLDOWN = 60


class RefreshMixin:
    async def refresh_all_devices(self: Amcrest2Mqtt) -> None:
        self.logger.info(f"refreshing device stats (every {self.device_interval} sec)")

        semaphore = asyncio.Semaphore(5)

        async def _refresh(device_id: str) -> None:
            async with semaphore:
                try:
                    changed = await self.build_device_states(device_id)
                    if changed:
                        await self.publish_device_state(device_id)
                except Exception as err:  # noqa: BLE001 - per-device isolation; one bad camera must not stop the others
                    self.logger.error(f"error refreshing device '{self.get_device_name(device_id)}': {err!r}")

        tasks = []
        for device_id in self.devices:
            if self.is_rebooting(device_id):
                self.logger.debug(f"skipping refresh for '{self.get_device_name(device_id)}', still rebooting")
                continue
            tasks.append(_refresh(device_id))
        if tasks:
            await asyncio.gather(*tasks)

    async def collect_all_device_events(self: Amcrest2Mqtt) -> None:
        """Keep exactly one live event-stream task per device.

        This used to ``asyncio.gather()`` every camera's stream. Each of those streams is
        effectively infinite, so the gather could not return -- and therefore this could not
        be called again to restart anything -- until EVERY camera's stream had ended. One
        camera dropping out stayed dead until the last of its siblings dropped out too.
        Measured in production: a camera gave up at 18:12 and was not restarted until 21:43,
        purely because three healthy cameras were still streaming in the same gather().

        Now each camera owns a task, and the 1s supervision tick in collect_events_loop()
        respawns whichever ones have finished. A camera going quiet costs that camera a few
        seconds, and costs the others nothing.
        """
        now = time.monotonic()

        for device_id in self.devices:
            if self.is_rebooting(device_id):
                self.logger.debug(f"skipping collecting events for '{self.get_device_name(device_id)}', still rebooting")
                continue

            task = self.event_tasks.get(device_id)
            if task is not None and not task.done():
                continue

            # get_events_from_device() already backs off between its own reconnect attempts,
            # but a camera that is hard-down still returns in ~20s. Without a cooldown here
            # that would be a give-up line every 20s, forever, for an unplugged camera.
            last_start = self.event_task_started.get(device_id, 0.0)
            if task is not None and now - last_start < EVENT_STREAM_RESPAWN_COOLDOWN:
                continue

            self.event_task_started[device_id] = now
            self.event_tasks[device_id] = asyncio.create_task(
                self._run_event_stream(device_id),
                name=f"event stream: {device_id}",
            )

    async def _run_event_stream(self: Amcrest2Mqtt, device_id: str) -> None:
        try:
            await self.get_events_from_device(device_id)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - per-device isolation; one bad camera must not stop the others
            self.logger.error(f"error collecting events for device '{self.get_device_name(device_id)}': {err!r}")

    async def cancel_all_device_events(self: Amcrest2Mqtt) -> None:
        """Cancel every live event-stream task. Called once on shutdown."""
        tasks = [task for task in self.event_tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.event_tasks.clear()
        self.event_task_started.clear()

    async def collect_all_device_snapshots(self: Amcrest2Mqtt) -> None:
        async def _collect_snapshot(device_id: str) -> None:
            try:
                await self.get_snapshot_from_device(device_id)
            except Exception as err:  # noqa: BLE001 - per-device isolation; one bad camera must not stop the others
                self.logger.error(f"error collecting snapshot for device '{self.get_device_name(device_id)}': {err!r}")

        tasks = []
        for device_id in self.devices:
            if self.is_rebooting(device_id):
                self.logger.debug(f"skipping snapshot for '{self.get_device_name(device_id)}', still rebooting")
                continue
            tasks.append(_collect_snapshot(device_id))

        if tasks:
            await asyncio.gather(*tasks)
