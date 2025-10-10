# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class RefreshMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    async def refresh_all_devices(self: Amcrest2Mqtt):
        self.logger.info(f"Refreshing all devices from Amcrest (every {self.device_interval} sec)")

        semaphore = asyncio.Semaphore(5)

        async def _refresh(device_id):
            async with semaphore:
                await asyncio.to_thread(self.build_device_states, device_id)

        tasks = []
        for device_id in self.devices:
            if not self.running:
                break
            if device_id == "service" or device_id in self.boosted:
                continue
            tasks.append(_refresh(device_id))

        if tasks:
            await asyncio.gather(*tasks)
