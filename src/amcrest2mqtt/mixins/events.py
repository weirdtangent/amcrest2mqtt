# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class EventsMixin:
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
            if event in ["motion", "human", "doorbell", "recording", "privacy_mode", "Reboot"]:
                if event == "recording":
                    if payload["file"].endswith(".jpg"):
                        image = await self.get_recorded_file(device_id, payload["file"])
                        if image:
                            if self.upsert_state(
                                device_id,
                                camera={"eventshot": image},
                                sensor={"event_time": datetime.now(timezone.utc).isoformat()},
                            ):
                                needs_publish.add(device_id)
                        event += ": snapshot"
                    elif payload["file"].endswith(".mp4"):
                        if "path" in self.config["media"] and self.states[device_id]["switch"].get("save_recordings", "OFF") == "ON":
                            await self.store_recording_in_media(device_id, payload["file"])
                        event += ": video"
                elif event == "motion":
                    region = payload["region"] if payload["state"] != "off" else "n/a"
                    if payload["file"].endswith(".jpg"):
                        image = await self.get_recorded_file(device_id, payload["file"])
                        if image:
                            if self.upsert_state(
                                device_id,
                                camera={"eventshot": image},
                                sensor={"event_time": datetime.now(timezone.utc).isoformat()},
                            ):
                                needs_publish.add(device_id)
                        event += ": snapshot"
                    elif payload["file"].endswith(".mp4"):
                        if "path" in self.config["media"] and self.states[device_id]["switch"].get("save_recordings", "OFF") == "ON":
                            await self.store_recording_in_media(device_id, payload["file"])
                        event += ": video"
                    if self.upsert_state(
                        device_id,
                        binary_sensor={"motion": payload["state"]},
                        sensor={"motion_region": region, "event_time": datetime.now(timezone.utc).isoformat()},
                    ):
                        needs_publish.add(device_id)
                    event += f": ({region}) - {payload["state"]}"
                else:
                    if isinstance(payload, str):
                        event += ": " + payload
                    elif isinstance(payload, dict):
                        if "state" in payload:
                            event += ": " + payload["state"]
                        if "action" in payload:
                            event += ": " + payload["action"]

                # other ways to infer "privacy mode" has been turned off and we need to update
                if event in ["motion", "human", "doorbell"] and states["switch"]["privacy"] != "OFF":
                    if self.upsert_state(device_id, switch={"privacy_mode": "OFF"}):
                        needs_publish.add(device_id)

                # record just these "events": text and time
                if self.upsert_state(
                    device_id,
                    sensor={
                        "event_text": event,
                        "event_time": datetime.now(timezone.utc).isoformat(),
                    },
                ):
                    needs_publish.add(device_id)
                self.logger.debug(f'processed event for "{self.get_device_name(device_id)}": {event} with {payload}')
            else:
                self.logger.debug(f'ignored event for "{self.get_device_name(device_id)}": {event} with {payload}')

        tasks = [self.publish_device_state(device_id) for device_id in needs_publish]
        if tasks:
            await asyncio.gather(*tasks)
