# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class RefreshMixin:
    async def refresh_all_devices(self: Amcrest2Mqtt) -> None:
        self.logger.info(f"Refreshing all devices from Amcrest (every {self.device_interval} sec)")

        semaphore = asyncio.Semaphore(5)

        async def _refresh(device_id: str) -> None:
            async with semaphore:
                await asyncio.to_thread(self.build_device_states, device_id)

        tasks = []
        for device_id in self.devices:
            if not self.running:
                break
            if device_id == "service":
                continue
            tasks.append(_refresh(device_id))

        if tasks:
            await asyncio.gather(*tasks)
