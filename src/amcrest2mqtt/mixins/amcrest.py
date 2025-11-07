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
        self.publish_service_state()

        seen_devices = set()

        for device in amcrest_devices.values():
            created = await self.build_component(device)
            if created:
                seen_devices.add(created)

        # Mark missing devices offline
        missing_devices = set(self.devices.keys()) - seen_devices
        for device_id in missing_devices:
            self.publish_device_availability(device_id, online=False)
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

    async def build_camera(self: Amcrest2Mqtt, device: dict) -> str:
        raw_id = cast(str, device["serial_number"])
        device_id = raw_id

        component = {
            "component_type": "camera",
            "name": device["device_name"],
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "video"),
            "topic": self.mqtt_helper.stat_t(device_id, "video"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "icon": "mdi:video",
            "via_device": self.mqtt_helper.service_slug,
            "device": {
                "name": device["device_name"],
                "identifiers": [self.mqtt_helper.device_slug(device_id)],
                "manufacturer": device["vendor"],
                "model": device["device_type"],
                "sw_version": device["software_version"],
                "hw_version": device["hardware_version"],
                "connections": [
                    ["host", device["host"]],
                    ["mac", device["network"]["mac"]],
                    ["ip address", device["network"]["ip_address"]],
                ],
                "configuration_url": f"http://{device['host']}/",
                "serial_number": device["serial_number"],
            },
        }
        if "webrtc" in self.amcrest_config:
            webrtc_config = self.amcrest_config["webrtc"]

            rtc_host = webrtc_config["host"]
            rtc_port = webrtc_config["port"]
            rtc_link = webrtc_config["link"]
            rtc_source = self.amcrest_config["webrtc"]["sources"][self.amcrest_devices[device_id]["config"]["index"]]

            if rtc_source:
                rtc_url = f"http://{rtc_host}:{rtc_port}/{rtc_link}?src={rtc_source}"
                component["url_topic"] = rtc_url

        modes = {}

        device_block = self.mqtt_helper.device_block(
            device["device_name"],
            self.mqtt_helper.device_slug(device_id),
            device["vendor"],
            device["software_version"],
        )

        modes["snapshot"] = {
            "component_type": "image",
            "name": "Timed snapshot",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "snapshot"),
            "image_topic": self.mqtt_helper.stat_t(device_id, "snapshot"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "image_encoding": "b64",
            "content_type": "image/jpeg",
            "icon": "mdi:camera",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["recording_time"] = {
            "component_type": "sensor",
            "name": "Recording time",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "recording_time"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "recording_time"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device_class": "timestamp",
            "icon": "mdi:clock",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["recording_url"] = {
            "component_type": "sensor",
            "name": "Recording url",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "recording_url"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "recording_url"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "clip_url": f"media-source://media_source/local/Videos/amcrest/{device["device_name"]}-latest.mp4",
            "icon": "mdi:web",
            "enabled_by_default": False,
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["privacy"] = {
            "component_type": "switch",
            "name": "Privacy mode",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "privacy"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "privacy"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "privacy"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:camera-outline",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["motion_detection"] = {
            "component_type": "switch",
            "name": "Motion detection",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_detection"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "motion_detection"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "motion_detection"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:motion-sensor",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["save_recordings"] = {
            "component_type": "switch",
            "name": "Save recordings",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "save_recordings"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "save_recordings"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "save_recordings"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:content-save-outline",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["motion"] = {
            "component_type": "binary_sensor",
            "name": "Motion sensor",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "motion"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "payload_on": True,
            "payload_off": False,
            "device_class": "motion",
            "icon": "mdi:eye-outline",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["motion_region"] = {
            "component_type": "sensor",
            "name": "Motion region",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_region"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "motion_region"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "icon": "mdi:map-marker",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["motion_snapshot"] = {
            "component_type": "image",
            "name": "Motion snapshot",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "motion_snapshot"),
            "image_topic": self.mqtt_helper.stat_t(device_id, "motion_snapshot"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "image_encoding": "b64",
            "content_type": "image/jpeg",
            "icon": "mdi:camera",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["storage_used"] = {
            "component_type": "sensor",
            "name": "Storage used",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_used"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_used"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GB",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["storage_used_pct"] = {
            "component_type": "sensor",
            "name": "Storage used %",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_used_pct"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_used_pct"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "state_class": "measurement",
            "unit_of_measurement": "%",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["storage_total"] = {
            "component_type": "sensor",
            "name": "Storage total",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "storage_total"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "storage_total"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GB",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        modes["event_text"] = {
            "component_type": "sensor",
            "name": "Last event",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "event_text"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "event_text"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "icon": "mdi:note",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }
        modes["event_time"] = {
            "component_type": "sensor",
            "name": "Last event time",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "event_time"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "event_time"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device_class": "timestamp",
            "icon": "mdi:clock",
            "via_device": self.mqtt_helper.service_slug,
            "device": device_block,
        }

        if device.get("is_doorbell", None):
            modes["doorbell"] = {
                "component_type": "binary_sensor",
                "name": "Doorbell" if device["device_name"] == "Doorbell" else f"{device["device_name"]} Doorbell",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "doorbell"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "doorbell"),
                "avty_t": self.mqtt_helper.avty_t(device_id),
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:doorbell",
                "via_device": self.mqtt_helper.service_slug,
                "device": device_block,
            }

        if device.get("is_ad410", None):
            modes["human"] = {
                "component_type": "binary_sensor",
                "name": "Human Sensor",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "human"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "binary_sensor", "human"),
                "avty_t": self.mqtt_helper.avty_t(device_id),
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:person",
                "via_device": self.mqtt_helper.service_slug,
                "device": device_block,
            }

        # store device and any "modes"
        self.upsert_device(device_id, component=component, modes=modes)

        # defaults - which build_device_states doesn't update (events do)
        self.upsert_state(
            device_id,
            internal={"discovered": False},
            camera={"video": None},
            image={"snapshot": None, "motion_snapshot": None},
            switch={"save_recordings": "ON" if "path" in self.config["media"] else "OFF"},
            binary_sensor={
                "motion": False,
                "doorbell": False,
                "human": False,
            },
            sensor={
                "motion_detection": "ON",
                "privacy": "OFF",
                "storage_used": 0,
                "storage_total": 0,
                "storage_used_pct": 0,
                "motion_region": "n/a",
                "event_text": "",
                "event_time": None,
                "recording_time": None,
                "recording_url": "",
            },
        )
        self.build_device_states(device_id)

        if not self.states[device_id]["internal"].get("discovered", None):
            self.logger.info(f'added new camera: "{device["device_name"]}" {device["vendor"]} {device["device_type"]}] ({device_id})')

        self.publish_device_discovery(device_id)
        self.publish_device_availability(device_id, online=True)
        self.publish_device_state(device_id)

        return device_id
