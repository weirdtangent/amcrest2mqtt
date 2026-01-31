import asyncio
from datetime import timezone
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class PublishMixin:

    # Service -------------------------------------------------------------------------------------

    async def publish_service_discovery(self: Amcrest2Mqtt) -> None:
        device_id = "service"

        device = {
            "stat_t": self.mqtt_helper.stat_t(device_id, "service"),
            "cmd_t": self.mqtt_helper.cmd_t(device_id),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device": {
                "name": self.service_name,
                "identifiers": [
                    self.mqtt_helper.service_slug,
                ],
                "manufacturer": "weirdTangent",
                "sw_version": self.config["version"],
            },
            "origin": {
                "name": self.service_name,
                "sw_version": self.config["version"],
                "support_url": "https://github.com/weirdtangent/amcrest2mqtt",
            },
            "qos": self.qos,
            "cmps": {
                "server": {
                    "p": "binary_sensor",
                    "name": self.service_name,
                    "uniq_id": self.mqtt_helper.svc_unique_id("server"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "server"),
                    "payload_on": "online",
                    "payload_off": "offline",
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                    "icon": "mdi:server",
                },
                "api_calls": {
                    "p": "sensor",
                    "name": "API calls today",
                    "uniq_id": self.mqtt_helper.svc_unique_id("api_calls"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "api_calls"),
                    "unit_of_measurement": "calls",
                    "entity_category": "diagnostic",
                    "state_class": "total_increasing",
                    "icon": "mdi:api",
                },
                "rate_limited": {
                    "p": "binary_sensor",
                    "name": "Rate limited",
                    "uniq_id": self.mqtt_helper.svc_unique_id("rate_limited"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "rate_limited"),
                    "payload_on": "YES",
                    "payload_off": "NO",
                    "device_class": "problem",
                    "entity_category": "diagnostic",
                    "icon": "mdi:speedometer-slow",
                },
                "last_call": {
                    "p": "sensor",
                    "name": "Last device check",
                    "uniq_id": self.mqtt_helper.svc_unique_id("last_call"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "last_call"),
                    "device_class": "timestamp",
                    "entity_category": "diagnostic",
                    "icon": "mdi:clock-outline",
                },
                "refresh_interval": {
                    "p": "number",
                    "name": "Refresh interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("refresh_interval"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "refresh_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "refresh_interval"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:timer-refresh",
                    "mode": "box",
                },
                "storage_interval": {
                    "p": "number",
                    "name": "Storage interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("storage_interval"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "storage_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "storage_interval"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:timer-refresh",
                    "mode": "box",
                },
                "snapshot_interval": {
                    "p": "number",
                    "name": "Snapshot interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("snapshot_interval"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "snapshot_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "snapshot_interval"),
                    "unit_of_measurement": "m",
                    "min": 1,
                    "max": 60,
                    "step": 1,
                    "icon": "mdi:lightning-bolt",
                    "mode": "box",
                },
            },
        }

        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = {k: v for k, v in device.items() if k != "p"}
        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(payload))
        self.upsert_state(device_id, internal={"discovered": True})

        self.logger.debug(f"discovery published for {self.service} ({self.mqtt_helper.service_slug})")

    async def publish_service_availability(self: Amcrest2Mqtt, status: str = "online") -> None:
        await asyncio.to_thread(self.mqtt_helper.safe_publish, self.mqtt_helper.avty_t("service"), status)

    async def publish_service_state(self: Amcrest2Mqtt) -> None:
        # we keep last_call_date in localtime so it rolls-over the api call counter
        # at the right time (midnight, local) but we want to send last_call_date
        # to HomeAssistant as UTC
        last_call_date = self.last_call_date
        local_tz = last_call_date.astimezone().tzinfo

        service = {
            "server": "online",
            "api_calls": self.api_calls,
            "last_call": last_call_date.replace(tzinfo=local_tz).astimezone(timezone.utc).isoformat(),
            "refresh_interval": self.device_interval,
            "storage_interval": self.storage_update_interval,
            "snapshot_interval": self.snapshot_update_interval,
            "rate_limited": "YES" if self.rate_limited else "NO",
        }

        for key, value in service.items():
            await asyncio.to_thread(
                self.mqtt_helper.safe_publish,
                self.mqtt_helper.stat_t("service", "service", key),
                json.dumps(value) if isinstance(value, dict) else value,
            )

    # Devices -------------------------------------------------------------------------------------

    async def publish_device_discovery(self: Amcrest2Mqtt, device_id: str) -> None:
        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = json.dumps(self.devices[device_id]["component"])

        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, payload)
        self.upsert_state(device_id, internal={"discovered": True})

    async def publish_device_availability(self: Amcrest2Mqtt, device_id: str, online: bool = True) -> None:
        topic = self.mqtt_helper.avty_t(device_id)
        payload = "online" if online else "offline"

        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, payload)

    async def publish_device_state(self: Amcrest2Mqtt, device_id: str, subject: str = "", sub: str = "") -> None:
        for state, value in list(self.states[device_id].items()):
            if subject and state != subject:
                continue
            # Attributes need to be published as a single JSON object to the attributes topic
            if state == "attributes" and isinstance(value, dict):
                topic = self.mqtt_helper.stat_t(device_id, "attributes")
                await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(value))
            elif isinstance(value, dict):
                for k, v in list(value.items()):
                    if sub and k != sub:
                        continue
                    topic = self.mqtt_helper.stat_t(device_id, state, k)
                    if isinstance(v, list):
                        v = json.dumps(v)
                    await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, v)
            else:
                topic = self.mqtt_helper.stat_t(device_id, state)
                await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, value)
