# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from deepmerge.merger import Merger
import ipaddress
import logging
import os
import pathlib
import signal
import socket
import threading
from types import FrameType
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt

READY_FILE = os.getenv("READY_FILE", "/tmp/amcrest2mqtt.ready")


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""

    pass


class HelpersMixin:
    def build_device_states(self: Amcrest2Mqtt, device_id: str) -> None:
        storage = self.get_storage_stats(device_id)
        privacy = self.get_privacy_mode(device_id)
        motion_detection = self.get_motion_detection(device_id)

        self.upsert_state(
            device_id,
            switch={
                "privacy": "ON" if privacy else "OFF",
                "motion_detection": "ON" if motion_detection else "OFF",
            },
            sensor={
                "storage_used": storage["used"],
                "storage_total": storage["total"],
                "storage_used_pct": storage["used_percent"],
            },
        )

    # send command to Amcrest -----------------------------------------------------------------------

    def handle_device_command(self: Amcrest2Mqtt, device_id: str, handler: str, message: str) -> None:
        match handler:
            case "save_recordings":
                if message == "ON" and "path" not in self.config["media"]:
                    self.logger.error("User tried to turn on save_recordings, but there is no media path set")
                    return
                self.upsert_state(device_id, switch={"save_recordings": message})
                self.publish_device_state(device_id)

    def handle_service_command(self: Amcrest2Mqtt, handler: str, message: str) -> None:
        match handler:
            case "storage_refresh":
                self.device_interval = int(message)
            case "device_list_refresh":
                self.device_list_interval = int(message)
            case "snapshot_refresh":
                self.snapshot_update_interval = int(message)
            case "refresh_device_list":
                if message == "refresh":
                    self.rediscover_all()
                else:
                    self.logger.error("[handler] unknown [message]")
                    return
            case _:
                self.logger.error(f"Unrecognized message to {self.mqtt_helper.service_slug}: {handler} -> {message}")
                return
        self.publish_service_state()

    def rediscover_all(self: Amcrest2Mqtt) -> None:
        self.publish_service_state()
        self.publish_service_discovery()
        for device_id in self.devices:
            if device_id == "service":
                continue
            self.publish_device_state(device_id)
            self.publish_device_discovery(device_id)

    # Utility functions ---------------------------------------------------------------------------

    def mark_ready(self: Amcrest2Mqtt) -> None:
        pathlib.Path(READY_FILE).touch()

    def heartbeat_ready(self: Amcrest2Mqtt) -> None:
        pathlib.Path(READY_FILE).touch()

    def read_file(self: Amcrest2Mqtt, file_name: str) -> str:
        with open(file_name, "r") as file:
            data = file.read().replace("\n", "")

        return data

    def mb_to_b(self: Amcrest2Mqtt, total: int) -> int:
        return total * 1024 * 1024

    def b_to_mb(self: Amcrest2Mqtt, total: int) -> float:
        return round(float(total) / 1024 / 1024, 2)

    def b_to_gb(self: Amcrest2Mqtt, total: int) -> float:
        return round(float(total) / 1024 / 1024 / 1024, 2)

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
                    return str(i[4][0])
        except socket.gaierror as e:
            raise Exception(f"Failed to resolve {string}: {e}")
        raise Exception(f"Failed to find IP address for {string}")

    def _csv(self: Amcrest2Mqtt, env_name: str) -> list[str] | None:
        v = os.getenv(env_name)
        if not v:
            return None
        return [s.strip() for s in v.split(",") if s.strip()]

    def load_config(self: Amcrest2Mqtt, config_arg: Any | None) -> dict[str, Any]:
        version = os.getenv("BLINK2MQTT_VERSION", self.read_file("VERSION"))
        config_from = "env"
        config: dict[str, str | bool | int | dict] = {}

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
        mqtt = cast(dict[str, Any], config.get("mqtt", {}))
        amcrest = cast(dict[str, Any], config.get("amcrest", {}))
        webrtc = cast(dict[str, Any], amcrest.get("webrtc", {}))
        media = cast(dict[str, Any], config.get("media", {}))

        # Determine media path (optional)
        media_path = media.get("path", None)
        if media_path:
            media_path = os.path.expanduser(media_path)
            media_path = os.path.abspath(media_path)

            if os.path.exists(media_path) and os.access(media_path, os.W_OK):
                media["path"] = media_path
                self.logger.info(f"Will be storing recordings in {media_path}, watch that it doesn't fill up your file system")
            else:
                self.logger.info("media_path not configured, not found, or is not writable. Will not be saving recordings")

        # fmt: off
        mqtt = {
            "host":            cast(str, mqtt.get("host")             or os.getenv("MQTT_HOST", "localhost")),
            "port":        int(cast(str, mqtt.get("port")             or os.getenv("MQTT_PORT", 1883))),
            "qos":         int(cast(str, mqtt.get("qos")              or os.getenv("MQTT_QOS", 0))),
            "username":                  mqtt.get("username")         or os.getenv("MQTT_USERNAME", ""),
            "password":                  mqtt.get("password")         or os.getenv("MQTT_PASSWORD", ""),
            "tls_enabled":               mqtt.get("tls_enabled")      or (os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"),
            "tls_ca_cert":               mqtt.get("tls_ca_cert")      or os.getenv("MQTT_TLS_CA_CERT"),
            "tls_cert":                  mqtt.get("tls_cert")         or os.getenv("MQTT_TLS_CERT"),
            "tls_key":                   mqtt.get("tls_key")          or os.getenv("MQTT_TLS_KEY"),
            "prefix":                    mqtt.get("prefix")           or os.getenv("MQTT_PREFIX", "amcrest2mqtt"),
            "discovery_prefix":          mqtt.get("discovery_prefix") or os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        }

        hosts = amcrest.get("hosts") or self._csv("AMCREST_HOSTS") or []
        names = amcrest.get("names") or self._csv("AMCREST_NAMES") or []
        sources = webrtc.get("sources") or self._csv("AMCREST_SOURCES") or []

        amcrest = {
            "hosts":                    hosts,
            "names":                    names,
            "port":                     int(cast(str, amcrest.get("port") or os.getenv("AMCREST_PORT", 80))),
            "username":                               amcrest.get("username") or os.getenv("AMCREST_USERNAME", ""),
            "password":                               amcrest.get("password") or os.getenv("AMCREST_PASSWORD", ""),
            "storage_update_interval":  int(cast(str, amcrest.get("storage_update_interval") or os.getenv("AMCREST_STORAGE_UPDATE_INTERVAL", 900))),
            "snapshot_update_interval": int(cast(str, amcrest.get("snapshot_update_interval") or os.getenv("AMCREST_SNAPSHOT_UPDATE_INTERVAL", 60))),
            "webrtc": {
                "host":                 webrtc.get("host") or os.getenv("AMCREST_WEBRTC_HOST", ""),
                "port":   int(cast(str, webrtc.get("port") or os.getenv("AMCREST_WEBRTC_PORT", 1984))),
                "link":                 webrtc.get("link") or os.getenv("AMCREST_WEBRTC_LINK", "webrtc"),
                "sources":              sources,
            },
        }

        config = {
            "mqtt":        mqtt,
            "amcrest":     amcrest,
            "debug":       config.get("debug", os.getenv("DEBUG", "").lower() == "true"),
            "hide_ts":     config.get("hide_ts", os.getenv("HIDE_TS", "").lower() == "true"),
            "timezone":    config.get("timezone", os.getenv("TZ", "UTC")),
            "media":       media,
            "config_from": config_from,
            "config_path": config_path,
            "version":     version,
        }
        # fmt: on

        # Validate required fields
        if not cast(dict, config["amcrest"]).get("username") or not cast(dict, config["amcrest"]).get("password"):
            raise ConfigError("`amcrest.username` and `amcrest.password` are required in config file or AMCREST_USERNAME and AMCREST_PASSWORD env vars")

        # Ensure list lengths match (sources is optional)
        if len(hosts) != len(names):
            raise ConfigError("`amcrest.hosts` and `amcrest.names` must be the same length")
        if sources and len(sources) != len(hosts):
            raise ConfigError("`amcrest.webrtc.sources` must match the length of `amcrest.hosts`/`amcrest.names` if provided")

        return config

    async def store_recording_in_media(self: Amcrest2Mqtt, device_id: str, amcrest_file: str) -> str | None:
        recording = self.get_recorded_file(device_id, amcrest_file, encode=False)
        if recording:
            name = self.get_device_name_slug(device_id)
            time = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = self.config["media"]["path"]
            file_name = f"{name}-{time}.mp4"
            file_path = Path(f"{path}/{file_name}")
            try:
                file_path.write_bytes(recording.encode("latin-1"))

                self.upsert_state(
                    device_id,
                    media={"recording": file_path},
                    sensor={"recording_time": datetime.now(timezone.utc).isoformat()},
                )
                local_file = Path(f"./{file_name}")
                latest_link = Path(f"{path}/{name}-latest.mp4")
                if latest_link.is_symlink():
                    latest_link.unlink()
                latest_link.symlink_to(local_file)

                if "media_source" in self.config["media"]:
                    url = f"{self.config["media"]["media_source"]}/{file_name}"
                    self.upsert_state(device_id, sensor={"recording_url": url})
                    return url
            except IOError as e:
                self.logger.error(f"Failed to save recordingt to {path}: {e}")
                return None

        self.logger.error(f"Failed to download recording from device {self.get_device_name(device_id)}")
        return None

    def _handle_signal(self: Amcrest2Mqtt, signum: int, frame: FrameType | None) -> Any:
        sig_name = signal.Signals(signum).name
        self.logger.warning(f"{sig_name} received - stopping service loop")
        self.running = False

        def _force_exit() -> None:
            self.logger.warning("Force-exiting process after signal")
            os._exit(0)

        threading.Timer(5.0, _force_exit).start()

    # Upsert devices and states -------------------------------------------------------------------

    def _assert_no_tuples(self: Amcrest2Mqtt, data: Any, path: str = "root") -> None:
        if isinstance(data, tuple):
            raise TypeError(f"⚠️ Found tuple at {path}: {data!r}")

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, tuple):
                    raise TypeError(f"⚠️ Found tuple key at {path}: {key!r}")
                self._assert_no_tuples(value, f"{path}.{key}")
        elif isinstance(data, list):
            for idx, value in enumerate(data):
                self._assert_no_tuples(value, f"{path}[{idx}]")

    def upsert_device(self: Amcrest2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> None:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],  # type conflicts: new wins
            ["override"],  # fallback
        )
        for section, data in kwargs.items():
            # Pre-merge check
            self._assert_no_tuples(data, f"device[{device_id}].{section}")
            merged = MERGER.merge(self.devices.get(device_id, {}), {section: data})
            # Post-merge check
            self._assert_no_tuples(merged, f"device[{device_id}].{section} (post-merge)")
            self.devices[device_id] = merged

    def upsert_state(self: Amcrest2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> None:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],  # type conflicts: new wins
            ["override"],  # fallback
        )
        for section, data in kwargs.items():
            self._assert_no_tuples(data, f"state[{device_id}].{section}")
            merged = MERGER.merge(self.states.get(device_id, {}), {section: data})
            self._assert_no_tuples(merged, f"state[{device_id}].{section} (post-merge)")
            self.states[device_id] = merged
