# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import ipaddress
import logging
import os
import socket
import yaml
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol

READY_FILE = os.getenv("READY_FILE", "/tmp/amcrest2mqtt.ready")


class UtilMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    def read_file(self: Amcrest2Mqtt, file_name: str) -> str:
        with open(file_name, "r") as file:
            data = file.read().replace("\n", "")

        return data

    def to_gb(self: Amcrest2Mqtt, total: [int]) -> str:
        return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))

    def is_ipv4(self: Amcrest2Mqtt, string: str) -> bool:
        try:
            ipaddress.IPv4Network(string)
            return True
        except ValueError:
            return False

    def get_ip_address(self: Amcrest2Mqtt, string: str) -> str:
        if self.is_ipv4(string):
            return string
        try:
            for i in socket.getaddrinfo(string, None):
                if i[0] == socket.AddressFamily.AF_INET:
                    return i[4][0]
        except socket.gaierror as e:
            raise Exception(f"Failed to resolve {string}: {e}")
        raise Exception(f"Failed to find IP address for {string}")

    def _csv(self: Amcrest2Mqtt, env_name):
        v = os.getenv(env_name)
        if not v:
            return None
        return [s.strip() for s in v.split(",") if s.strip()]

    def load_config(self: Amcrest2Mqtt, config_arg=None) -> list[str, Any]:
        version = os.getenv("BLINK2MQTT_VERSION", self.read_file("VERSION"))
        config_from = "env"
        config = {}

        # Determine config file path
        config_path = config_arg or "/config"
        config_path = os.path.expanduser(config_path)
        config_path = os.path.abspath(config_path)

        if os.path.isdir(config_path):
            config_file = os.path.join(config_path, "config.yaml")
        elif os.path.isfile(config_path):
            config_file = config_path
            config_path = os.path.dirname(config_file)
        else:
            # If it's not a valid path but looks like a filename, handle gracefully
            if config_path.endswith(".yaml"):
                config_file = config_path
            else:
                config_file = os.path.join(config_path, "config.yaml")

        # Try to load from YAML
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = yaml.safe_load(f) or {}
                config_from = "file"
            except Exception as e:
                logging.warning(f"Failed to load config from {config_file}: {e}")
        else:
            logging.warning(f"Config file not found at {config_file}, falling back to environment vars")

        # Merge with environment vars (env vars override nothing if file exists)
        mqtt = config.get("mqtt", {})
        amcrest = config.get("amcrest", {})
        webrtc = amcrest.get("webrtc", {})

        # fmt: off
        mqtt = {
            "host":             mqtt.get("host")             or os.getenv("MQTT_HOST", "localhost"),
            "port":         int(mqtt.get("port")             or os.getenv("MQTT_PORT", 1883)),
            "qos":          int(mqtt.get("qos")              or os.getenv("MQTT_QOS", 0)),
            "username":         mqtt.get("username")         or os.getenv("MQTT_USERNAME", ""),
            "password":         mqtt.get("password")         or os.getenv("MQTT_PASSWORD", ""),
            "tls_enabled":      mqtt.get("tls_enabled")      or (os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"),
            "tls_ca_cert":      mqtt.get("tls_ca_cert")      or os.getenv("MQTT_TLS_CA_CERT"),
            "tls_cert":         mqtt.get("tls_cert")         or os.getenv("MQTT_TLS_CERT"),
            "tls_key":          mqtt.get("tls_key")          or os.getenv("MQTT_TLS_KEY"),
            "prefix":           mqtt.get("prefix")           or os.getenv("MQTT_PREFIX", "amcrest2mqtt"),
            "discovery_prefix": mqtt.get("discovery_prefix") or os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        }

        hosts = amcrest.get("hosts") or self._csv("AMCREST_HOSTS") or []
        names = amcrest.get("names") or self._csv("AMCREST_NAMES") or []
        sources = webrtc.get("sources") or self._csv("AMCREST_SOURCES") or []

        amcrest = {
            "hosts":                    hosts,
            "names":                    names,
            "port":                     int(amcrest.get("port") or os.getenv("AMCREST_PORT", 80)),
            "username":                     amcrest.get("username") or os.getenv("AMCREST_USERNAME", ""),
            "password":                     amcrest.get("password") or os.getenv("AMCREST_PASSWORD", ""),
            "storage_update_interval":  int(amcrest.get("storage_update_interval") or os.getenv("AMCREST_STORAGE_UPDATE_INTERVAL", 900)),
            "snapshot_update_interval": int(amcrest.get("snapshot_update_interval") or os.getenv("AMCREST_SNAPSHOT_UPDATE_INTERVAL", 60)),
            "webrtc": {
                "host":       webrtc.get("host") or os.getenv("AMCREST_WEBRTC_HOST", ""),
                "port":   int(webrtc.get("port") or os.getenv("AMCREST_WEBRTC_PORT", 1984)),
                "link":       webrtc.get("link") or os.getenv("AMCREST_WEBRTC_LINK", "webrtc"),
                "sources":    sources,
            },
        }

        config = {
            "mqtt":        mqtt,
            "amcrest":     amcrest,
            "debug":       config.get("debug", os.getenv("DEBUG", "").lower() == "true"),
            "hide_ts":     config.get("hide_ts", os.getenv("HIDE_TS", "").lower() == "true"),
            "timezone":    config.get("timezone", os.getenv("TZ", "UTC")),
            "config_from": config_from,
            "config_path": config_path,
            "version":     version,
        }
        # fmt: on

        # Validate required fields
        if not config["amcrest"].get("username") or not config["amcrest"].get("password"):
            raise ValueError("`amcrest.username` and `amcrest.password` are required in config file or AMCREST_USERNAME and AMCREST_PASSWORD env vars")

        # Ensure list lengths match (sources is optional)
        if len(hosts) != len(names):
            raise ValueError("`amcrest.hosts` and `amcrest.names` must be the same length")
        if sources and len(sources) != len(hosts):
            raise ValueError("`amcrest.webrtc.sources` must match the length of `amcrest.hosts`/`amcrest.names` if provided")

        return config
