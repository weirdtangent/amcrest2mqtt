# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class AmcrestMixin:
    async def setup_device_list(self: Amcrest2Mqtt) -> None:
        self.logger.debug("setting up device list from config")

        amcrest_devices = await self.connect_to_devices()
        await self.publish_service_state()

        seen_devices: set[str] = set()

        # Build all components concurrently
        tasks = [(device, self.build_component(device)) for device in amcrest_devices.values()]
        results = await asyncio.gather(*[task[1] for task in tasks], return_exceptions=True)

        # Collect successful device IDs
        for (device, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                device_name = device.get("device_name", "unknown")
                device_id = device.get("serial_number", "unknown")
                exception_type = type(result).__name__
                self.logger.error(f"error during build_component for device '{device_name}' ({device_id}): " f"{exception_type}: {result}", exc_info=True)
            elif result and isinstance(result, str):
                seen_devices.add(result)

        # Mark missing devices offline
        missing_devices = set(self.devices.keys()) - seen_devices
        for device_id in missing_devices:
            await self.publish_device_availability(device_id, online=False)
            self.logger.warning(f"device {device_id} not seen in Amcrest API list — marked offline")

        # Handle first discovery completion
        if not self.discovery_complete:
            await asyncio.sleep(1)
            self.logger.info("device setup and discovery is done")
            self.discovery_complete = True

    # convert Amcrest device capabilities into MQTT components
    async def build_component(self: Amcrest2Mqtt, device: dict) -> str:
        device_class = self.classify_device(device)
        match device_class:
            case "camera":
                return await self.build_camera(device)
        return ""

    def classify_device(self: Amcrest2Mqtt, device: dict) -> str:
        if device["device_type"].upper() in [
            "IPM-721",
            "IPM-HX1",
            "IP2M-841",
            "IP2M-842",
            "IP3M-941",
            "IP3M-943",
            "IP3M-956",
            "IP3M-956E",
            "IP3M-HX2",
            "IP4M-1026B",
            "IP4M-1041B",
            "IP4M-1051B",
            "IP5M-1176EB",
            "IP8M-2496EB",
            "IP8M-T2499EW-28M",
            "XVR DAHUA 5104S",
        ]:
            return "camera"
        else:
            self.logger.error(f"device you specified is not a supported model: {device["device_type"]}")
            return ""

    async def build_camera(self: Amcrest2Mqtt, camera: dict) -> str:
        raw_id = cast(str, camera["serial_number"]).strip()
        device_id = raw_id

        rtc_url = ""
        if "webrtc" in self.amcrest_config:
            webrtc_config = self.amcrest_config["webrtc"]

            rtc_host = webrtc_config["host"]
            rtc_port = webrtc_config["port"]
            rtc_link = webrtc_config["link"]
            rtc_source = self.amcrest_config["webrtc"]["sources"][self.amcrest_devices[device_id]["config"]["index"]]

            if rtc_source:
                rtc_url = f"http://{rtc_host}:{rtc_port}/{rtc_link}?src={rtc_source}"

        device = {
            "stat_t": self.mqtt_helper.stat_t(device_id, "state"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device": {
                "name": camera["device_name"],
                "identifiers": [
                    self.mqtt_helper.device_slug(device_id),
                    raw_id,
                ],
                "manufacturer": camera["vendor"],
                "model": camera["device_type"],
                "sw_version": camera["software_version"],
                "hw_version": camera["hardware_version"],
                "connections": [
                    ["host", camera["host"]],
                    ["mac", camera["network"]["mac"]],
                    ["ip address", camera["network"]["ip_address"]],
                ],
                "configuration_url": f"http://{camera['host']}/",
                "serial_number": camera["serial_number"],
                "via_device": self.service,
            },
            "origin": {"name": self.service_name, "sw": self.config["version"], "support_url": "https://github.com/weirdTangent/amcrest2mqtt"},
            "qos": self.qos,
            "cmps": {
                "camera": {
                    "p": "camera",
                    "name": "Camera",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "camera"),
                    "topic": self.mqtt_helper.stat_t(device_id, "camera", "snapshot"),
                    "sup_str": True,
                    "str_src": rtc_url,
                    "image_encoding": "b64",
                    "icon": "mdi:video",
                },
                "snapshot": {
                    "p": "image",
                    "name": "Snapshot",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "snapshot"),
                    "image_topic": self.mqtt_helper.stat_t(device_id, "camera", "snapshot"),
                    "image_encoding": "b64",
                    "icon": "mdi:camera",
                },
                "motion": {
                    "p": "binary_sensor",
                    "name": "Motion",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "motion"),
                    "jsn_atr_t": self.mqtt_helper.stat_t(device_id, "attributes"),
                    "payload_on": True,
                    "payload_off": False,
                    "device_class": "motion",
                    "icon": "mdi:eye-outline",
                },
                "motion_region": {
                    "p": "sensor",
                    "name": "Motion region",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_region"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "motion_region"),
                    "icon": "mdi:map-marker",
                },
                "motion_snapshot": {
                    "p": "image",
                    "name": "Motion snapshot",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_snapshot"),
                    "image_topic": self.mqtt_helper.stat_t(device_id, "image", "motion_snapshot"),
                    "image_encoding": "b64",
                    "icon": "mdi:camera",
                },
                "reboot": {
                    "p": "button",
                    "name": "Reboot",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "reboot"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "button", "reboot"),
                    "payload_press": "PRESS",
                    "icon": "mdi:restart",
                    "entity_category": "diagnostic",
                },
                "privacy": {
                    "p": "switch",
                    "name": "Privacy mode",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "privacy"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "privacy"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "privacy"),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "switch",
                    "icon": "mdi:camera-outline",
                },
                "motion_detection": {
                    "p": "switch",
                    "name": "Motion detection",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_detection"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "motion_detection"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "motion_detection"),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "switch",
                    "icon": "mdi:motion-sensor",
                },
                "event_text": {
                    "p": "sensor",
                    "name": "Last event",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "event_text"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "event_text"),
                    "icon": "mdi:note",
                },
                "save_recordings": {
                    "p": "switch",
                    "name": "Save recordings",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "save_recordings"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "save_recordings"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "save_recordings"),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "switch",
                    "icon": "mdi:content-save-outline",
                },
                "storage_used": {
                    "p": "sensor",
                    "name": "Storage used",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_used"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_used"),
                    "device_class": "data_size",
                    "state_class": "measurement",
                    "unit_of_measurement": "GB",
                    "entity_category": "diagnostic",
                    "icon": "mdi:micro-sd",
                },
                "storage_used_pct": {
                    "p": "sensor",
                    "name": "Storage used %",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_used_pct"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_used_pct"),
                    "state_class": "measurement",
                    "unit_of_measurement": "%",
                    "entity_category": "diagnostic",
                    "icon": "mdi:micro-sd",
                },
                "storage_total": {
                    "p": "sensor",
                    "name": "Storage total",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_total"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_total"),
                    "device_class": "data_size",
                    "state_class": "measurement",
                    "unit_of_measurement": "GB",
                    "entity_category": "diagnostic",
                    "icon": "mdi:micro-sd",
                },
            },
        }

        if "media" in self.config and "media_source" in self.config["media"]:
            device["cmps"]["recording_url"] = {
                "p": "sensor",
                "name": "Recording url",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "recording_url"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "recording_url"),
                "icon": "mdi:web",
            }

        if camera.get("is_doorbell", None):
            device["cmps"]["doorbell"] = {
                "p": "binary_sensor",
                "name": "Doorbell" if camera["device_name"] == "Doorbell" else f"{camera["device_name"]} Doorbell",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "doorbell"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "doorbell"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:doorbell",
            }

        if camera.get("is_ad410", None):
            device["cmps"]["human"] = {
                "p": "binary_sensor",
                "name": "Human Sensor",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "human"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "human"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:person",
            }

        self.upsert_device(device_id, component=device)
        # initial states because many of these won't update until something happens
        # or this is the only time we'll ever set them
        self.upsert_state(
            device_id,
            internal={},
            webrtc=rtc_url,
            switch={"save_recordings": "ON" if "path" in self.config["media"] else "OFF"},
            binary_sensor={"motion": False},
            sensor={"motion_region": ""},
            attributes={"recording_url": f"{self.config["media"]["media_source"]}/{camera["device_name"]}-latest.mp4"},
            image={"motion_snapshot": ""},
        )

        if not self.is_discovered(device_id):
            self.logger.info(f'added new camera: "{camera["device_name"]}" {camera["vendor"]} {camera["device_type"]}] ({device_id})')
            await self.publish_device_discovery(device_id)

        await self.publish_device_availability(device_id, online=True)
        await self.publish_device_state(device_id)

        return device_id
