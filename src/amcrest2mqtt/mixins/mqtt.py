# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
from typing import TYPE_CHECKING, Any

from mqtt_helper import BaseMqttMixin
from paho.mqtt.client import Client, MQTTMessage

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class MqttMixin(BaseMqttMixin):
    def mqtt_subscription_topics(self: Amcrest2Mqtt) -> list[str]:
        return [
            "homeassistant/status",
            f"{self.mqtt_helper.service_slug}/service/+/set",
            f"{self.mqtt_helper.service_slug}/service/+/command",
            f"{self.mqtt_helper.service_slug}/+/switch/+/set",
            f"{self.mqtt_helper.service_slug}/+/button/+/set",
        ]

    async def mqtt_on_message(self: Amcrest2Mqtt, client: Client, userdata: Any, msg: MQTTMessage) -> None:
        topic = msg.topic
        components = topic.split("/")

        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            try:
                payload = msg.payload.decode("utf-8")
            except Exception:
                self.logger.warning("failed to decode MQTT payload: {err}")
                return None

        if components[0] == self.mqtt_config["discovery_prefix"]:
            return await self.handle_homeassistant_message(payload)

        if components[0] == self.mqtt_helper.service_slug and components[1] == "service":
            return await self.handle_service_command(components[2], payload)

        if components[0] == self.mqtt_helper.service_slug:
            return await self.handle_device_topic(components, payload)

        self.logger.debug(f"ignoring unrelated MQTT topic: {topic}")

    async def handle_homeassistant_message(self: Amcrest2Mqtt, payload: str) -> None:
        if payload == "online":
            await self.rediscover_all()
            self.logger.info("home Assistant came (back?) online — resending device discovery")

    async def handle_device_topic(self: Amcrest2Mqtt, components: list[str], payload: str) -> None:
        parsed = self._parse_device_topic(components)
        if not parsed:
            return

        vendor, device_id, attribute = parsed
        if not vendor or not vendor.startswith(self.mqtt_helper.service_slug):
            self.logger.info(f"ignoring non-Amcrest device command, got vendor {vendor}")
            return
        if not device_id or not attribute:
            self.logger.error(f"failed to parse device_id and/or payload from mqtt topic components: {components}")
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"got Mqtt message for unknown device: ({device_id})")
            return

        self.logger.info(f"got message for '{self.get_device_name(device_id)}': set {components[-2]} to {payload}")
        await self.handle_device_command(device_id, attribute, payload)

    def _parse_device_topic(self: Amcrest2Mqtt, components: list[str]) -> list[str | None] | None:
        try:
            if components[-1] != "set":
                return None

            # Example topics:
            # amcrest2mqtt/amcrest2mqtt_2BEFD0C907BB6BF2/switch/save_recordings/set
            # amcrest2mqtt/amcrest2mqtt_2BEFD0C907BB6BF2/button/reboot/set

            vendor, device_id = components[1].split("_", 1)
            attribute = components[-2]

            return [vendor, device_id, attribute]

        except Exception as err:
            self.logger.warning(f"malformed device topic with {components}: {err!r}")
            return []

    def safe_split_device(self: Amcrest2Mqtt, topic: str, segment: str) -> list[str]:
        try:
            return segment.split("-", 1)
        except ValueError as err:
            self.logger.warning(f"ignoring malformed topic {topic}: {err!r}")
            return []
