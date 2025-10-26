# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class AmcrestMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    async def setup_device_list(self: Amcrest2Mqtt) -> None:
        self.logger.info("Setting up device list from config")

        devices = await self.connect_to_devices()
        self.publish_service_state()

        seen_devices = set()

        for device in devices.values():
            created = await self.build_component(device)
            if created:
                seen_devices.add(created)

        # Mark missing devices offline
        missing_devices = set(self.devices.keys()) - seen_devices
        for device_id in missing_devices:
            self.publish_device_availability(device_id, online=False)
            self.logger.warning(f"Device {device_id} not seen in Amcrest API list — marked offline")

        # Handle first discovery completion
        if not self.discovery_complete:
            await asyncio.sleep(1)
            self.logger.info("First-time device setup and discovery is done")
            self.discovery_complete = True

    # convert Amcrest device capabilities into MQTT components
    async def build_component(self: Amcrest2Mqtt, device: dict) -> str | None:
        device_class = self.classify_device(device)
        match device_class:
            case "camera":
                return await self.build_camera(device)

    def classify_device(self: Amcrest2Mqtt, device: dict) -> str | None:
        return "camera"

    async def build_camera(self: Amcrest2Mqtt, device: dict) -> str:
        raw_id = device["serial_number"]
        device_id = raw_id

        component = {
            "component_type": "camera",
            "name": device["device_name"],
            "uniq_id": f"{self.get_device_slug(device_id, 'video')}",
            "topic": self.get_state_topic(device_id, "video"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "json_attributes_topic": self.get_state_topic(device_id, "attributes"),
            "icon": "mdi:video",
            "via_device": self.get_service_device(),
            "device": {
                "name": device["device_name"],
                "identifiers": [self.get_device_slug(device_id)],
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
            rtc_source = webrtc_config["sources"].pop(0)
            rtc_url = f"http://{rtc_host}:{rtc_port}/{rtc_link}?src={rtc_source}"
            component["url_topic"] = rtc_url
        modes = {}

        device_block = self.get_device_block(
            self.get_device_slug(device_id),
            device["device_name"],
            device["vendor"],
            device["device_type"],
        )

        modes["snapshot"] = {
            "component_type": "image",
            "name": "Timed snapshot",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'snapshot')}",
            "topic": self.get_state_topic(device_id, "snapshot"),
            "image_encoding": "b64",
            "content_type": "image/jpeg",
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "json_attributes_topic": self.get_state_topic(device_id, "attributes"),
            "icon": "mdi:camera",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["recording_time"] = {
            "component_type": "sensor",
            "name": "Recording time",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'recording_time')}",
            "stat_t": self.get_state_topic(device_id, "recording_time"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "json_attributes_topic": self.get_state_topic(device_id, "attributes"),
            "device_class": "timestamp",
            "icon": "mdi:clock",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["recording_url"] = {
            "component_type": "sensor",
            "name": "Recording url",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'recording_url')}",
            "stat_t": self.get_state_topic(device_id, "recording_url"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "clip_url": f"media-source://media_source/local/Videos/amcrest/{device["device_name"]}-latest.mp4",
            "json_attributes_topic": self.get_state_topic(device_id, "attributes"),
            "icon": "mdi:web",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["privacy"] = {
            "component_type": "switch",
            "name": "Privacy mode",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'privacy')}",
            "stat_t": self.get_state_topic(device_id, "switch", "privacy"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "cmd_t": self.get_command_topic(device_id, "switch", "privacy"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:camera-outline",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["motion_detection"] = {
            "component_type": "switch",
            "name": "Motion detection",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'motion_detection')}",
            "stat_t": self.get_state_topic(device_id, "switch", "motion_detection"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "cmd_t": self.get_command_topic(device_id, "switch", "motion_detection"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:motion-sensor",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["save_recordings"] = {
            "component_type": "switch",
            "name": "Save recordings",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'save_recordings')}",
            "stat_t": self.get_state_topic(device_id, "switch", "save_recordings"),
            "avty_t": self.get_state_topic(device_id, "internal"),
            "avty_tpl": "{{ value_json.media_path }}",
            "cmd_t": self.get_command_topic(device_id, "switch", "save_recordings"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "switch",
            "icon": "mdi:content-save-outline",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["motion"] = {
            "component_type": "binary_sensor",
            "name": "Motion sensor",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'motion')}",
            "stat_t": self.get_state_topic(device_id, "binary_sensor", "motion"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "payload_on": True,
            "payload_off": False,
            "device_class": "motion",
            "icon": "mdi:eye-outline",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["motion_region"] = {
            "component_type": "sensor",
            "name": "Motion region",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'motion_region')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "motion_region"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "icon": "mdi:map-marker",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["motion_snapshot"] = {
            "component_type": "image",
            "name": "Motion snapshot",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'motion_snapshot')}",
            "topic": self.get_state_topic(device_id, "motion_snapshot"),
            "image_encoding": "b64",
            "content_type": "image/jpeg",
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "json_attributes_topic": self.get_state_topic(device_id, "attributes"),
            "icon": "mdi:camera",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["storage_used"] = {
            "component_type": "sensor",
            "name": "Storage used",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'storage_used')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "storage_used"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GB",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["storage_used_pct"] = {
            "component_type": "sensor",
            "name": "Storage used %",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'storage_used_pct')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "storage_used_pct"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "state_class": "measurement",
            "unit_of_measurement": "%",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["storage_total"] = {
            "component_type": "sensor",
            "name": "Storage total",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'storage_total')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "storage_total"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "device_class": "data_size",
            "state_class": "measurement",
            "unit_of_measurement": "GB",
            "entity_category": "diagnostic",
            "icon": "mdi:micro-sd",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        modes["event_text"] = {
            "component_type": "sensor",
            "name": "Last event",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'event_text')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "event_text"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "icon": "mdi:note",
            "via_device": self.get_service_device(),
            "device": device_block,
        }
        modes["event_time"] = {
            "component_type": "sensor",
            "name": "Last event time",
            "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'event_time')}",
            "stat_t": self.get_state_topic(device_id, "sensor", "event_time"),
            "avty_t": self.get_state_topic(device_id, "attributes"),
            "avty_tpl": "{{ value_json.camera }}",
            "device_class": "timestamp",
            "icon": "mdi:clock",
            "via_device": self.get_service_device(),
            "device": device_block,
        }

        if device.get("is_doorbell", None):
            modes["doorbell"] = {
                "component_type": "binary_sensor",
                "name": "Doorbell" if device["device_name"] == "Doorbell" else f"{device["device_name"]} Doorbell",
                "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'doorbell')}",
                "stat_t": self.get_state_topic(device_id, "binary_sensor", "doorbell"),
                "avty_t": self.get_state_topic(device_id, "attributes"),
                "avty_tpl": "{{ value_json.camera }}",
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:doorbell",
                "via_device": self.get_service_device(),
                "device": device_block,
            }

        if device.get("is_ad410", None):
            modes["human"] = {
                "component_type": "binary_sensor",
                "name": "Human Sensor",
                "uniq_id": f"{self.service_slug}_{self.get_device_slug(device_id, 'human')}",
                "stat_t": self.get_state_topic(device_id, "binary_sensor", "human"),
                "avty_t": self.get_state_topic(device_id, "attributes"),
                "avty_tpl": "{{ value_json.camera }}",
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:person",
                "via_device": self.get_service_device(),
                "device": device_block,
            }

        # defaults - which build_device_states doesn't update (events do)
        self.upsert_state(
            device_id,
            internal={"discovered": False, "media_path": True if "path" in self.config["media"] else False},
            camera={"video": None},
            image={"snapshot": None, "motion_snapshot": None},
            switch={"save_recordings": "ON" if "path" in self.config["media"] else "OFF"},
            binary_sensor={
                "motion": False,
                "doorbell": False,
                "human": False,
            },
            sensor={
                "motion_region": "n/a",
                "event_text": None,
                "event_time": None,
                "recording_time": None,
                "recording_url": None,
            },
        )
        self.upsert_device(device_id, component=component, modes=modes)
        self.build_device_states(device_id)

        if not self.states[device_id]["internal"].get("discovered", None):
            self.logger.info(f'Added new camera: "{device["device_name"]}" {device["vendor"]} {device["device_type"]}] ({device_id})')

        self.publish_device_discovery(device_id)
        self.publish_device_availability(device_id, online=True)
        self.publish_device_state(device_id)

        return device_id

    def publish_device_discovery(self: Amcrest2Mqtt, device_id: str) -> None:
        def _publish_one(dev_id: str, defn: dict, suffix: str | None = None):
            # Compute a per-mode device_id for topic namespacing
            eff_device_id = dev_id if not suffix else f"{dev_id}_{suffix}"

            # Grab this component's discovery topic
            topic = self.get_discovery_topic(defn["component_type"], eff_device_id)

            # Shallow copy to avoid mutating source
            payload = {k: v for k, v in defn.items() if k != "component_type"}

            # Publish discovery
            self.mqtt_safe_publish(topic, json.dumps(payload), retain=True)

            # Mark discovered in state (per published entity)
            self.states.setdefault(eff_device_id, {}).setdefault("internal", {})["discovered"] = 1

        component = self.get_component(device_id)
        _publish_one(device_id, component, suffix=None)

        # Publish any modes (0..n)
        modes = self.get_modes(device_id)
        for slug, mode in modes.items():
            _publish_one(device_id, mode, suffix=slug)

    def publish_device_state(self: Amcrest2Mqtt, device_id: str) -> None:
        def _publish_one(dev_id: str, mode_name: str, defn):
            # Grab device states and this component's state topic
            topic = self.get_device_state_topic(dev_id, mode_name)
            if not topic:
                self.logger.error(f"Why is topic emtpy for device {dev_id} and mode {mode_name}")

            # Shallow copy to avoid mutating source
            flat = None
            if isinstance(defn, dict):
                payload = {k: v for k, v in defn.items() if k != "component_type"}
                flat = None

                if not payload:
                    flat = ""
                elif not isinstance(payload, dict):
                    flat = payload
                else:
                    flat = {}
                    for k, v in payload.items():
                        if k == "component_type":
                            continue
                        flat[k] = v

                # Add metadata
                meta = states.get("meta")
                if isinstance(meta, dict) and "last_update" in meta:
                    flat["last_update"] = meta["last_update"]
                self.mqtt_safe_publish(topic, json.dumps(flat), retain=True)
            else:
                flat = defn
                self.mqtt_safe_publish(topic, flat, retain=True)

        if not self.is_discovered(device_id):
            self.logger.debug(f"[device state] Discovery not complete for {device_id} yet, holding off on sending state")
            return

        states = self.states.get(device_id, None)

        if self.devices[device_id]["component"]["component_type"] != "camera":
            _publish_one(device_id, "", states[self.get_component_type(device_id)])

        # Publish any modes (0..n)
        modes = self.get_modes(device_id)
        for name, mode in modes.items():
            component_type = mode["component_type"]
            type_states = states[component_type][name] if isinstance(states[component_type], dict) else states[component_type]
            _publish_one(device_id, name, type_states)

    def publish_device_availability(self: Amcrest2Mqtt, device_id, online: bool = True):
        payload = "online" if online else "offline"

        # if state and availability are the SAME, we don't want to
        # overwrite the big json state with just online/offline
        stat_t = self.get_device_state_topic(device_id)
        avty_t = self.get_device_availability_topic(device_id)
        if stat_t and avty_t and stat_t == avty_t:
            self.logger.info(f"Skipping availability because state_topic and avail_topic are the same: {stat_t}")
            return

        self.mqtt_safe_publish(avty_t, payload, retain=True)
