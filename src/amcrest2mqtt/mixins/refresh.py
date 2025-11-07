# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class RefreshMixin:
    async def refresh_all_devices(self: Amcrest2Mqtt) -> None:
        self.logger.info(f"refreshing device stats (every {self.device_interval} sec)")

        semaphore = asyncio.Semaphore(5)

        async def _refresh(device_id: str) -> None:
            async with semaphore:
                changed = await asyncio.to_thread(self.build_device_states, device_id)
                if changed:
                    await asyncio.to_thread(self.publish_device_state, device_id)

        tasks = []
        for device_id in self.devices:
            if self.is_rebooting(device_id):
                self.logger.debug(f"skipping refresh for {self.get_device_name(device_id)}, still rebooting")
                continue
            tasks.append(_refresh(device_id))
        if tasks:
            await asyncio.gather(*tasks)
