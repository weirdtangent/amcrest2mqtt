# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class EventsMixin:
    async def collect_all_device_events(self: Amcrest2Mqtt) -> None:
        tasks = [self.get_events_from_device(device_id) for device_id in self.amcrest_devices]
        await asyncio.gather(*tasks)

    async def check_for_events(self: Amcrest2Mqtt) -> None:
        needs_publish = set()

        while device_event := self.get_next_event():
            if "device_id" not in device_event:
                continue

            device_id = str(device_event["device_id"])
            event = str(device_event["event"])
            payload = device_event["payload"]

            states = self.states[device_id]

            # if one of our known sensors
            if event in ["motion", "human", "doorbell", "recording", "privacy_mode"]:
                if event == "recording":
                    if payload["file"].endswith(".jpg"):
                        image = self.get_recorded_file(device_id, payload["file"])
                        if image:
                            self.upsert_state(
                                device_id,
                                camera={"eventshot": image},
                                sensor={"event_time": datetime.now(timezone.utc).isoformat()},
                            )
                    elif payload["file"].endswith(".mp4"):
                        if "path" in self.config["media"] and self.states[device_id]["switch"]["save_recordings"] == "ON":
                            await self.store_recording_in_media(device_id, payload["file"])
                elif event == "motion":
                    self.upsert_state(
                        device_id,
                        binary_sensor={"motion": payload["state"]},
                        sensor={
                            "motion_region": payload["region"] if payload["state"] != "off" else "n/a",
                            "event_time": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                else:
                    self.upsert_state(device_id, sensor={event: payload})

                # other ways to infer "privacy mode" has been turned off and we need to update
                if event in ["motion", "human", "doorbell"] and states["switch"]["privacy"] != "OFF":
                    self.upsert_state(device_id, switch={"privacy_mode": "OFF"})

            # send everything to the device's event_text/time
            self.logger.debug(f'got event {{{event}: {payload}}} for "{self.get_device_name(device_id)}"')
            self.upsert_state(
                device_id,
                sensor={
                    "event_text": f"{event}: {payload}",
                    "event_time": datetime.now(timezone.utc).isoformat(),
                },
            )
            needs_publish.add(device_id)

        for id in needs_publish:
            self.publish_device_state(id)
