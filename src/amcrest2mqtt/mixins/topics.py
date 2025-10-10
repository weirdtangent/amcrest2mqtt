# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import random
import string
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class TopicsMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    def get_new_client_id(self: Amcrest2Mqtt):
        return self.mqtt_config["prefix"] + "-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    # Slug strings --------------------------------------------------------------------------------

    def get_device_slug(self: Amcrest2Mqtt, device_id: str, type: Optional[str] = None) -> str:
        return "_".join(filter(None, [self.service_slug, device_id.replace(":", ""), type]))

    def get_vendor_device_slug(self: Amcrest2Mqtt, device_id):
        return f"{self.service_slug}-{device_id.replace(':', '')}"

    # Topic strings -------------------------------------------------------------------------------

    def get_service_device(self: Amcrest2Mqtt):
        return self.service

    def get_service_topic(self: Amcrest2Mqtt, topic):
        return f"{self.service_slug}/status/{topic}"

    def get_device_topic(self: Amcrest2Mqtt, component_type, device_id, *parts) -> str:
        if device_id == "service":
            return "/".join([self.service_slug, *map(str, parts)])

        device_slug = self.get_device_slug(device_id)
        return "/".join([self.service_slug, component_type, device_slug, *map(str, parts)])

    def get_discovery_topic(self: Amcrest2Mqtt, component, item) -> str:
        return f"{self.mqtt_config['discovery_prefix']}/{component}/{item}/config"

    def get_state_topic(self: Amcrest2Mqtt, device_id, category, item=None) -> str:
        topic = f"{self.service_slug}/{category}" if device_id == "service" else f"{self.service_slug}/devices/{self.get_device_slug(device_id)}/{category}"
        return f"{topic}/{item}" if item else topic

    def get_availability_topic(self: Amcrest2Mqtt, device_id, category="availability", item=None) -> str:
        topic = f"{self.service_slug}/{category}" if device_id == "service" else f"{self.service_slug}/devices/{self.get_device_slug(device_id)}/{category}"
        return f"{topic}/{item}" if item else topic

    def get_attribute_topic(self: Amcrest2Mqtt, device_id, category, item, attribute) -> str:
        if device_id == "service":
            return f"{self.service_slug}/{category}/{item}/{attribute}"

        device_entry = self.devices.get(device_id, {})
        component = device_entry.get("component") or device_entry.get("component_type") or category
        return f"{self.mqtt_config['discovery_prefix']}/{component}/{self.get_device_slug(device_id)}/{item}/{attribute}"

    def get_command_topic(self: Amcrest2Mqtt, device_id, category, command="set") -> str:
        if device_id == "service":
            return f"{self.service_slug}/service/{category}/{command}"

        # if category is not passed in, device must exist already
        if not category:
            category = self.devices[device_id]["component"]["component_type"]

        return f"{self.service_slug}/{category}/{self.get_device_slug(device_id)}/{command}"

    # Device propertiesi --------------------------------------------------------------------------

    def get_device_name(self: Amcrest2Mqtt, device_id):
        return self.devices[device_id]["component"]["name"]

    def get_component(self: Amcrest2Mqtt, device_id):
        return self.devices[device_id]["component"]

    def get_component_type(self: Amcrest2Mqtt, device_id):
        return self.devices[device_id]["component"]["component_type"]

    def get_modes(self: "Amcrest2Mqtt", device_id):
        return self.devices[device_id].get("modes", {})

    def get_mode(self: "Amcrest2Mqtt", device_id, mode_name):
        modes = self.devices[device_id].get("modes", {})
        return modes.get(mode_name, {})

    def get_last_update(self: "Amcrest2Mqtt", device_id: str) -> str:
        return self.states[device_id]["internal"].get("last_update", None)

    def is_discovered(self: "Amcrest2Mqtt", device_id: str) -> bool:
        return self.states[device_id]["internal"].get("discovered", False)

    def get_device_state_topic(self: "Amcrest2Mqtt", device_id, mode_name=None):
        component = self.get_mode(device_id, mode_name) if mode_name else self.get_component(device_id)

        if component["component_type"] == "camera":
            return component.get("topic", None)
        else:
            return component.get("stat_t", component.get("state_topic", None))

    def get_device_availability_topic(self: Amcrest2Mqtt, device_id):
        component = self.get_component(device_id)
        return component.get("avty_t", component.get("availability_topic", None))

    # Misc helpers --------------------------------------------------------------------------------

    def get_device_block(self: Amcrest2Mqtt, id, name, vendor="Amcrest", sku=None):
        device = {"name": name, "identifiers": [id], "manufacturer": vendor}

        if sku:
            device["model"] = sku

        if name == self.service_name:
            device.update(
                {
                    "suggested_area": "House",
                    "manufacturer": "weirdTangent",
                    "sw_version": self.config["version"],
                }
            )
        return device
