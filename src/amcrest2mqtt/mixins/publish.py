from datetime import datetime
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class PublishMixin:

    # Service -------------------------------------------------------------------------------------

    def publish_service_discovery(self: Amcrest2Mqtt) -> None:
        device_block = self.mqtt_helper.device_block(
            self.service_name,
            self.mqtt_helper.service_slug,
            "weirdTangent",
            self.config["version"],
        )

        self.logger.info("Publishing service entity")
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("binary_sensor", "service"),
            payload=json.dumps(
                {
                    "name": self.service_name,
                    "uniq_id": self.mqtt_helper.svc_unique_id("service"),
                    "stat_t": self.mqtt_helper.svc_t("service"),
                    "device_class": "connectivity",
                    "icon": "mdi:server",
                    "device": device_block,
                    "origin": {
                        "name": self.service_name,
                        "sw_version": self.config["version"],
                        "support_url": "https://github.com/weirdtangent/amcrest2mqtt",
                    },
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )

        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("sensor", "api_calls"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} API Calls Today",
                    "uniq_id": self.mqtt_helper.svc_unique_id("api_calls"),
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "api_calls"),
                    "json_attr_t": self.mqtt_helper.attr_t("service", "service", "api_calls", "attributes"),
                    "unit_of_measurement": "calls",
                    "icon": "mdi:api",
                    "state_class": "total_increasing",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("binary_sensor", "rate_limited"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} Rate Limited by Amcrest",
                    "uniq_id": self.mqtt_helper.svc_unique_id("rate_limited"),
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "rate_limited"),
                    "json_attr_t": self.mqtt_helper.attr_t("service", "service", "rate_limited", "attributes"),
                    "payload_on": "YES",
                    "payload_off": "NO",
                    "device_class": "problem",
                    "icon": "mdi:speedometer-slow",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("number", "storage_refresh"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} Device Refresh Interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("storage_refresh"),
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "storage_refresh"),
                    "json_attr_t": self.mqtt_helper.attr_t("service", "service", "storage_refresh", "attributes"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "storage_refresh"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:timer-refresh",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("number", "device_list_refresh"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} Device List Refresh Interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("device_list_refresh"),
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "device_list_refresh"),
                    "json_attr_t": self.mqtt_helper.attr_t("service", "service", "device_list_refresh", "attributes"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "device_list_refresh"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:format-list-bulleted",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("number", "snapshot_refresh"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} Snapshot Refresh Interval",
                    "uniq_id": self.mqtt_helper.svc_unique_id("snapshot_refresh"),
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "snapshot_refresh"),
                    "json_attr_t": self.mqtt_helper.attr_t("service", "service", "snapshot_refresh", "attributes"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "snapshot_refresh"),
                    "unit_of_measurement": "m",
                    "min": 1,
                    "max": 60,
                    "step": 1,
                    "icon": "mdi:lightning-bolt",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.mqtt_safe_publish(
            topic=self.mqtt_helper.disc_t("button", "refresh_device_list"),
            payload=json.dumps(
                {
                    "name": f"{self.service_name} Refresh Device List",
                    "uniq_id": self.mqtt_helper.svc_unique_id("refresh_device_list"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "refresh_device_list", "command"),
                    "payload_press": "refresh",
                    "icon": "mdi:refresh",
                    "device": device_block,
                }
            ),
            qos=self.mqtt_config["qos"],
            retain=True,
        )
        self.logger.debug(f"[HA] Discovery published for {self.service} ({self.mqtt_helper.service_slug})")

    def publish_service_availability(self: Amcrest2Mqtt, avail: str = "online") -> None:
        self.mqtt_safe_publish(self.mqtt_helper.svc_t("status"), avail, qos=self.qos, retain=True)

    def publish_service_state(self: Amcrest2Mqtt) -> None:
        service = {
            "state": "online",
            "api_calls": {
                "api_calls": self.get_api_calls(),
                "last_api_call": self.get_last_call_date(),
            },
            "rate_limited": "YES" if self.is_rate_limited() else "NO",
            "storage_refresh": self.device_interval,
            "device_list_refresh": self.device_list_interval,
            "snapshot_refresh": self.snapshot_update_interval,
        }

        payload: Any
        for key, value in service.items():
            if isinstance(value, dict):
                payload = value.get(key)
                if isinstance(payload, datetime):
                    payload = payload.isoformat()
                payload = json.dumps(payload)
            else:
                payload = str(value)

            self.mqtt_safe_publish(
                self.mqtt_helper.stat_t("service", "service", key),
                payload,
                qos=self.mqtt_config["qos"],
                retain=True,
            )

    # Devices -------------------------------------------------------------------------------------

    def publish_device_discovery(self: Amcrest2Mqtt, device_id: str) -> None:
        def _publish_one(dev_id: str, defn: dict, suffix: str = "") -> None:
            # Compute a per-mode device_id for topic namespacing
            eff_device_id = dev_id if not suffix else f"{dev_id}_{suffix}"

            # Grab this component's discovery topic
            topic = self.mqtt_helper.disc_t(defn["component_type"], f"{dev_id}_{suffix}" if suffix else dev_id)

            # Shallow copy to avoid mutating source
            payload = {k: v for k, v in defn.items() if k != "component_type"}

            # Publish discovery
            self.mqtt_safe_publish(topic, json.dumps(payload), retain=True)

            # Mark discovered in state (per published entity)
            self.states.setdefault(eff_device_id, {}).setdefault("internal", {})["discovered"] = 1

        component = self.get_component(device_id)
        _publish_one(device_id, component)

        # Publish any modes (0..n)
        modes = self.get_modes(device_id)
        for slug, mode in modes.items():
            _publish_one(device_id, mode, suffix=slug)

    def publish_device_availability(self: Amcrest2Mqtt, device_id: str, online: bool = True) -> None:
        payload = "online" if online else "offline"

        avty_t = self.get_device_availability_topic(device_id)
        self.mqtt_safe_publish(avty_t, payload, retain=True)

    def publish_device_state(self: Amcrest2Mqtt, device_id: str) -> None:
        def _publish_one(dev_id: str, defn: str | dict[str, Any], suffix: str = "") -> None:
            # Grab this component's state topic
            topic = self.get_device_state_topic(dev_id, suffix)

            # Shallow copy to avoid mutating source
            if isinstance(defn, dict):
                flat: dict[str, Any] = {k: v for k, v in defn.items() if k != "component_type"}

                # Add metadata
                meta = self.states[dev_id].get("meta")
                if isinstance(meta, dict) and "last_update" in meta:
                    flat["last_update"] = meta["last_update"]
                self.mqtt_safe_publish(topic, json.dumps(flat), retain=True)
            else:
                self.mqtt_safe_publish(topic, defn, retain=True)

        if not self.is_discovered(device_id):
            self.logger.debug(f"[device state] Discovery not complete for {device_id} yet, holding off on sending state")
            return

        states = self.states[device_id]
        _publish_one(device_id, states[self.get_component_type(device_id)])

        # Publish any modes (0..n)
        modes = self.get_modes(device_id)
        for name, mode in modes.items():
            component_type = mode["component_type"]

            # if no state yet, skip it
            if component_type not in states or (isinstance(states[component_type], dict) and name not in states[component_type]):
                continue

            type_states = states[component_type][name] if isinstance(states[component_type], dict) else states[component_type]
            _publish_one(device_id, type_states, name)
