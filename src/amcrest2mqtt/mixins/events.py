# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from datetime import datetime
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class EventsMixin:
    async def publish_vision_request(self: Amcrest2Mqtt, device_id: str, image_b64: str, source: str) -> None:
        if not self.config.get("vision_request"):
            return
        topic = f"{self.service}/vision/request"
        now = datetime.now()
        payload = {
            "camera_id": device_id,
            "camera_name": self.get_device_name(device_id),
            "event_id": now.strftime("%Y%m%d-%H%M%S"),
            "image_b64": image_b64,
            "timestamp": now.isoformat(timespec="seconds"),
            "source": source,
        }
        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(payload))
        self.logger.debug(f"published vision request for '{self.get_device_name(device_id)}' ({source})")

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
                if event == "recording" and "file" in payload:
                    self.logger.debug(f'recording event for \'{self.get_device_name(device_id)}\': {payload["file"]}')
                    if payload["file"].endswith(".jpg"):
                        image = await self.get_recorded_file(device_id, payload["file"])
                        if image:
                            await self.publish_vision_request(device_id, image, "recording_snapshot")
                            needs_publish.add(device_id)
                            event += ": snapshot"
                    elif payload["file"].endswith(".mp4"):
                        if "path" in self.config["media"] and self.states[device_id]["switch"].get("save_recordings", "OFF") == "ON":
                            file_name = await self.store_recording_in_media(device_id, payload["file"])
                            if file_name:
                                self.upsert_state(device_id, attributes={"recording_url": f"{self.config["media"]["media_source"]}/{file_name}"})
                                needs_publish.add(device_id)
                        event += ": video"
                elif event == "motion":
                    region = payload["region"] if payload["state"] != "off" else ""
                    motion = f": {region}" if region else f": {payload["state"]}"

                    self.upsert_state(
                        device_id,
                        binary_sensor={"motion": payload["state"] == "on"},
                        attributes={"region": region},
                    )
                    needs_publish.add(device_id)
                    event += motion

                    # publish latest snapshot as vision request on motion start
                    if payload["state"] == "on":
                        snapshot = states.get("image", {}).get("snapshot")
                        if snapshot:
                            await self.publish_vision_request(device_id, snapshot, "motion_snapshot")
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
                self.upsert_state(device_id, sensor={"event_text": event})
                needs_publish.add(device_id)
                self.logger.debug(f"processed event for '{self.get_device_name(device_id)}': {event} with {payload}")
            else:
                # we ignore these on purpose, but log if something unexpected comes through
                if event not in ["NtpAdjustTime", "TimeChange", "RtspSessionDisconnect"]:
                    self.logger.debug(f"ignored unexpected event for '{self.get_device_name(device_id)}': {event} with {payload}")

        tasks = [self.publish_device_state(device_id) for device_id in needs_publish]
        if tasks:
            await asyncio.gather(*tasks)
