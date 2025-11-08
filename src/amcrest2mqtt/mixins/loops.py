# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class LoopsMixin:
    async def device_loop(self: Amcrest2Mqtt) -> None:
        while self.running:
            await self.refresh_all_devices()
            try:
                await asyncio.sleep(self.device_interval)
            except asyncio.CancelledError:
                self.logger.debug("device_loop cancelled during sleep")
                break

    async def collect_events_loop(self: Amcrest2Mqtt) -> None:
        while self.running:
            await self.collect_all_device_events()
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.logger.debug("collect_events_loop cancelled during sleep")
                break

    async def check_event_queue_loop(self: Amcrest2Mqtt) -> None:
        while self.running:
            await self.check_for_events()
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.logger.debug("check_event_queue_loop cancelled during sleep")
                break

    async def collect_snapshots_loop(self: Amcrest2Mqtt) -> None:
        while self.running:
            await self.collect_all_device_snapshots()
            try:
                await asyncio.sleep(self.snapshot_update_interval * 60)
            except asyncio.CancelledError:
                self.logger.debug("collect_snapshots_loop cancelled during sleep")
                break

    async def heartbeat(self: Amcrest2Mqtt) -> None:
        while self.running:
            try:
                await asyncio.sleep(60)
                self.heartbeat_ready()
            except asyncio.CancelledError:
                self.logger.debug("heartbeat cancelled during sleep")
                break

    # main loop
    async def main_loop(self: Amcrest2Mqtt) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self.handle_signal)
            except Exception:
                self.logger.debug(f"Cannot install handler for {sig}")

        await self.setup_device_list()
        self.running = True
        self.mark_ready()

        tasks = [
            asyncio.create_task(self.device_loop(), name="device_loop"),
            asyncio.create_task(self.collect_events_loop(), name="collect events loop"),
            asyncio.create_task(self.check_event_queue_loop(), name="check events queue loop"),
            asyncio.create_task(self.collect_snapshots_loop(), name="collect snapshot loop"),
            asyncio.create_task(self.heartbeat(), name="heartbeat"),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.logger.warning("Main loop cancelled — shutting down...")
        except Exception as err:
            self.logger.exception(f"Unhandled exception in main loop: {err}")
            self.running = False
        finally:
            self.logger.info("All loops terminated — cleanup complete.")
