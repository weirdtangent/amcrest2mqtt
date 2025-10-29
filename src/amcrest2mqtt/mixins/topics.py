# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import re
from typing import TYPE_CHECKING, cast, Any

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class TopicsMixin:

    # Device properties --------------------------------------------------------------------------

    def get_device_name(self: Amcrest2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"]["device"]["name"])

    def get_device_name_slug(self: Amcrest2Mqtt, device_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", self.get_device_name(device_id).lower())

    def get_component(self: Amcrest2Mqtt, device_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id]["component"])

    def get_component_type(self: Amcrest2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"].get("component_type", "unknown"))

    def get_modes(self: Amcrest2Mqtt, device_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id]["modes"])

    def get_mode(self: Amcrest2Mqtt, device_id: str, mode_name: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id]["modes"][mode_name])

    def is_discovered(self: Amcrest2Mqtt, device_id: str) -> bool:
        return cast(bool, self.states[device_id]["internal"].get("discovered", False))

    def get_device_state_topic(self: Amcrest2Mqtt, device_id: str, mode_name: str = "") -> str:
        component = self.get_mode(device_id, mode_name) if mode_name else self.get_component(device_id)

        match component["component_type"]:
            case "camera":
                return cast(str, component["topic"])
            case "image":
                return cast(str, component["image_topic"])
            case _:
                return cast(str, component.get("stat_t") or component.get("state_topic"))

    def get_device_image_topic(self: Amcrest2Mqtt, device_id: str) -> str:
        component = self.get_component(device_id)
        return cast(str, component["topic"])

    def get_device_availability_topic(self: Amcrest2Mqtt, device_id: str) -> str:
        component = self.get_component(device_id)
        return cast(str, component.get("avty_t") or component.get("availability_topic"))
