# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class EventsMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    async def collect_all_device_events(self: Amcrest2Mqtt) -> None:
        tasks = [self.get_events_from_device(device_id) for device_id in self.amcrest_devices]
        await asyncio.gather(*tasks)

    async def check_for_events(self: Amcrest2Mqtt) -> None:
        try:
            while device_event := self.get_next_event():
                if device_event is None:
                    break
                if "device_id" not in device_event:
                    self.logger(f"Got event, but missing device_id: {device_event}")
                    continue

                device_id = device_event["device_id"]
                event = device_event["event"]
                payload = device_event["payload"]

                device_states = self.states[device_id]

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
                    else:
                        self.logger.info(f"Got event for {self.get_device_name(device_id)}: {event} - {payload}")
                        if event == "motion":
                            self.upsert_state(
                                device_id,
                                binary_sensor={"motion": payload["state"]},
                                sensor={
                                    "motion_region": payload["region"] if payload["state"] != "off" else "",
                                    "event_time": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                        else:
                            self.upsert_state(device_id, sensor={event: payload})

                    # other ways to infer "privacy mode" is off and needs updating
                    if event in ["motion", "human", "doorbell"] and device_states["switch"]["privacy"] != "OFF":
                        self.upsert_state(device_id, switch={"privacy_mode": "OFF"})

                # send everything to the device's event_text/time
                self.logger.debug(f'Got {{{event}: {payload}}} for "{self.get_device_name(device_id)}"')
                self.upsert_state(
                    device_id,
                    sensor={
                        "event_text": f"{event}: {payload}",
                        "event_time": datetime.now(timezone.utc).isoformat(),
                    },
                )

                self.publish_device_state(device_id)
        except Exception as err:
            self.logger.error(err, exc_info=True)
