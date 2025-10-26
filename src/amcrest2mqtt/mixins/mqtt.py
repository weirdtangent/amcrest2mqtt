# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import ssl
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class MqttMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    def mqttc_create(self: Amcrest2Mqtt):
        self.mqttc = mqtt.Client(
            client_id=self.client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            reconnect_on_failure=False,
            protocol=mqtt.MQTTv5,
        )

        if self.mqtt_config.get("tls_enabled"):
            self.mqttc.tls_set(
                ca_certs=self.mqtt_config.get("tls_ca_cert"),
                certfile=self.mqtt_config.get("tls_cert"),
                keyfile=self.mqtt_config.get("tls_key"),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )
        if self.mqtt_config.get("username") or self.mqtt_config.get("password"):
            self.mqttc.username_pw_set(
                username=self.mqtt_config.get("username") or None,
                password=self.mqtt_config.get("password") or None,
            )

        self.mqttc.on_connect = self.mqtt_on_connect
        self.mqttc.on_disconnect = self.mqtt_on_disconnect
        self.mqttc.on_message = self.mqtt_on_message
        self.mqttc.on_subscribe = self.mqtt_on_subscribe
        self.mqttc.on_log = self.mqtt_on_log

        # Define a "last will" message (LWT):
        self.mqttc.will_set(self.get_service_topic("status"), "offline", qos=self.qos, retain=True)

        try:
            host = self.mqtt_config.get("host")
            port = self.mqtt_config.get("port")
            self.logger.info(f"Connecting to MQTT broker at {host}:{port} as {self.client_id}")

            props = Properties(PacketTypes.CONNECT)
            props.SessionExpiryInterval = 0

            self.mqttc.connect(host=host, port=port, keepalive=60, properties=props)
            self.logger.info(f"Successful connection to {host} MQTT broker")

            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.error(f"Failed to connect to MQTT host {host}: {error}")
            self.running = False
        except Exception as error:
            self.logger.error(f"Network problem trying to connect to MQTT host {host}: {error}")
            self.running = False

    def mqtt_on_connect(self: Amcrest2Mqtt, client, userdata, flags, reason_code, properties):
        if reason_code.value != 0:
            self.logger.error(f"MQTT failed to connect ({reason_code.getName()})")
            self.running = False
            return

        self.publish_service_discovery()
        self.publish_service_availability()
        self.publish_service_state()

        self.logger.info("Subscribing to topics on MQTT")
        client.subscribe("homeassistant/status")
        client.subscribe(f"{self.service_slug}/service/+/set")
        client.subscribe(f"{self.service_slug}/service/+/command")
        client.subscribe(f"{self.service_slug}/switch/#")

    def mqtt_on_disconnect(self: Amcrest2Mqtt, client, userdata, flags, reason_code, properties):
        if reason_code.value != 0:
            self.logger.error(f"MQTT lost connection ({reason_code.getName()})")
        else:
            self.logger.info("Closed MQTT connection")

        if self.running and (self.mqtt_connect_time is None or time.time() > self.mqtt_connect_time + 10):
            # clear connect_time and try to restart
            self.mqtt_connect_time = None
            while not self.mqtt_connect_time:
                try:
                    self.client_id = self.get_new_client_id()
                    self.mqttc_create()
                except Exception as e:
                    self.logger.error(f"Trouble reconnecting to MQTT (retry in 10 s): {e}")
                    time.sleep(10)
        else:
            self.logger.info("MQTT disconnect — stopping service loop")
            self.running = False

    def mqtt_on_log(self: Amcrest2Mqtt, client, userdata, paho_log_level, msg):
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            self.logger.error(f"MQTT logged: {msg}")
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            self.logger.warning(f"MQTT logged: {msg}")

    def mqtt_on_message(self: Amcrest2Mqtt, client, userdata, msg):
        topic = msg.topic
        payload = self._decode_payload(msg.payload)
        components = topic.split("/")

        # Dispatch based on type of message
        if components[0] == self.mqtt_config["discovery_prefix"]:
            return self._handle_homeassistant_message(payload)

        if components[0] == self.service_slug and components[1] == "service":
            return self.handle_service_command(components[2], payload)

        if components[0] == self.service_slug:
            return self._handle_device_topic(components, payload)

        # self.logger.debug(f"Ignoring unrelated MQTT topic: {topic}")

    def _decode_payload(self: Amcrest2Mqtt, raw):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            # Fallback: try to decode as UTF-8 string
            try:
                return raw.decode("utf-8")
            except Exception:
                self.logger.warning("Failed to decode MQTT payload")
                return None

    def _handle_homeassistant_message(self: Amcrest2Mqtt, payload):
        if payload == "online":
            self.rediscover_all()
            self.logger.info("Home Assistant came online — rediscovering devices")

    def _handle_device_topic(self: Amcrest2Mqtt, components, payload):
        vendor, device_id, attribute = self._parse_device_topic(components)
        if not vendor or not vendor.startswith(self.service_slug):
            self.logger.debug(f"Ignoring non-Amcrest device topic: {'/'.join(components)}")
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"Got MQTT message for unknown device: {device_id}")
            return

        self.logger.debug(f"Got message for {self.get_device_name(device_id)}: {attribute} => {payload}")
        self.handle_device_command(device_id, attribute, payload)

    def _parse_device_topic(self: Amcrest2Mqtt, components):
        try:
            if components[-1] != "set":
                return (None, None, None)

            # Example topics:
            # amcrest2mqtt/light/amcrest2mqtt_2BEFD0C907BB6BF2/set
            # amcrest2mqtt/light/amcrest2mqtt_2BEFD0C907BB6BF2/save_recordings/set

            # Case 1: .../<device>/<attribute>set
            if len(components) >= 5 and "_" in components[-3]:
                vendor, device_id = components[-3].split("_", 1)
                attribute = components[-2]
            # Case 2: .../<device>/<attribute>/set
            elif len(components) >= 4 and "_" in components[-2]:
                vendor, device_id = components[-2].split("_", 1)
                attribute = None

            else:
                raise ValueError(f"Malformed topic (expected underscore): {'/'.join(components)}")

            return (vendor, device_id, attribute)

        except Exception as e:
            self.logger.warning(f"Malformed device topic: {components} ({e})")
            return (None, None, None)

    def safe_split_device(self: Amcrest2Mqtt, topic, segment):
        """Split a topic segment into (vendor, device_id) safely."""
        try:
            return segment.split("-", 1)
        except ValueError:
            self.logger.warning(f"Ignoring malformed topic: {topic}")
            return (None, None)

    def mqtt_on_subscribe(self: Amcrest2Mqtt, client, userdata, mid, reason_code_list, properties):
        reason_names = [rc.getName() for rc in reason_code_list]
        joined = "; ".join(reason_names) if reason_names else "none"
        self.logger.debug(f"MQTT subscribed (mid={mid}): {joined}")

    def mqtt_safe_publish(self: Amcrest2Mqtt, topic, payload, **kwargs):
        if not topic:
            raise ValueError(f"topic {topic} is empty, why bother")
        if isinstance(payload, dict) and ("component" in payload or "//////" in payload):
            self.logger.warning("Questionable payload includes 'component' or string of slashes - wont't send to HA")
            self.logger.warning(f"topic: {topic}")
            self.logger.warning(f"payload: {payload}")
            raise ValueError("Possible invalid payload. topic: {topic} payload: {payload}")
        try:
            self.mqttc.publish(topic, payload, **kwargs)
        except Exception as e:
            self.logger.warning(f"MQTT publish failed for {topic}: {e}")
