# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from deepmerge.merger import Merger
import ipaddress
import os
import pathlib
import re
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
    async def build_device_states(self: Amcrest2Mqtt, device_id: str) -> bool:
        if self.is_rebooting(device_id):
            self.logger.debug(f"skipping device states for {self.get_device_name(device_id)}, still rebooting")
            return False

        # get properties from device
        storage, privacy, motion_detection = await asyncio.gather(
            self.get_storage_stats(device_id),
            self.get_privacy_mode(device_id),
            self.get_motion_detection(device_id),
        )

        changed = self.upsert_state(
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
        return changed

    # send command to Amcrest -----------------------------------------------------------------------

    async def handle_device_command(self: Amcrest2Mqtt, device_id: str, handler: str, message: Any) -> None:
        match handler:
            case "save_recordings":
                if message == "ON" and "path" not in self.config["media"]:
                    self.logger.error("user tried to turn on save_recordings, but there is no media path set")
                    return
                self.upsert_state(device_id, switch={"save_recordings": message})
                await self.publish_device_state(device_id)
            case "motion_detection":
                await self.set_motion_detection(device_id, message == "ON")
            case "privacy":
                await self.set_privacy_mode(device_id, message == "ON")
            case "reboot":
                self.reboot_device(device_id)

    async def handle_service_command(self: Amcrest2Mqtt, handler: str, message: Any) -> None:
        match handler:
            case "storage_interval":
                self.device_interval = int(message)
                self.logger.info(f"storage_interval updated to be {message}")
            case "rescan_interval":
                self.device_list_interval = int(message)
                self.logger.info(f"rescan_interval updated to be {message}")
            case "snapshot_refresh":
                self.snapshot_update_interval = int(message)
                self.logger.info(f"snapshot_interval updated to be {message}")
            case _:
                self.logger.error(f"unrecognized message to {self.mqtt_helper.service_slug}: {handler} -> {message}")
                return
        await self.publish_service_state()

    async def rediscover_all(self: Amcrest2Mqtt) -> None:
        await self.publish_service_discovery()
        await self.publish_service_state()
        for device_id in self.devices:
            await self.publish_device_discovery(device_id)
            await self.publish_device_state(device_id)

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

    async def get_ip_address(self: Amcrest2Mqtt, string: str) -> str:
        if self.is_ipv4(string):
            return string

        try:
            infos = await self.loop.getaddrinfo(string, None, family=socket.AF_INET)
            # getaddrinfo returns a list of 5-tuples; [4][0] holds the IP string
            return infos[0][4][0]
        except socket.gaierror as err:
            raise Exception(f"failed to resolve {string}: {err}") from err
        except IndexError:
            raise Exception(f"failed to find IP address for {string}")

    def list_from_env(self: Amcrest2Mqtt, env_name: str) -> list[str]:
        v = os.getenv(env_name)
        return [] if not v else [s.strip() for s in v.split(",") if s.strip()]

    def load_config(self: Amcrest2Mqtt, config_arg: Any | None) -> dict[str, Any]:
        version = os.getenv("APP_VERSION", self.read_file("VERSION"))
        tier = os.getenv("APP_TIER", "prod")
        if tier == "dev":
            version += ":DEV"

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

        # Try to load from YAML
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = yaml.safe_load(f) or {}
                config_from = "file"
            except Exception as err:
                raise ConfigError(f"found {config_file} but failed to load: {err}")
        else:
            self.logger.info(f"config file not found at {config_file}, falling back to environment vars")

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
                media.setdefault("max_size", 25)
                self.logger.info(f"storing recordings in {media_path} up to {media["max_size"]} MB per file. Watch that it doesn't fill up the file system")
            else:
                self.logger.info("media_path not configured, not found, or is not writable. Will not be saving recordings")

        # fmt: off
        mqtt = {
            "host":             str(mqtt.get("host")             or os.getenv("MQTT_HOST", "localhost")),
            "port":         int(str(mqtt.get("port")             or os.getenv("MQTT_PORT", 1883))),
            "qos":          int(str(mqtt.get("qos")              or os.getenv("MQTT_QOS", 0))),
            "username":         str(mqtt.get("username")         or os.getenv("MQTT_USERNAME", "")),
            "password":         str(mqtt.get("password")         or os.getenv("MQTT_PASSWORD", "")),
            "tls_enabled":     bool(mqtt.get("tls_enabled")      or (os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true")),
            "tls_ca_cert":      str(mqtt.get("tls_ca_cert")      or os.getenv("MQTT_TLS_CA_CERT")),
            "tls_cert":         str(mqtt.get("tls_cert")         or os.getenv("MQTT_TLS_CERT")),
            "tls_key":          str(mqtt.get("tls_key")          or os.getenv("MQTT_TLS_KEY")),
            "prefix":           str(mqtt.get("prefix")           or os.getenv("MQTT_PREFIX", "amcrest2mqtt")),
            "discovery_prefix": str(mqtt.get("discovery_prefix") or os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")),
        }

        hosts = list[str](amcrest.get("hosts") or self.list_from_env("AMCREST_HOSTS"))
        names = list[str](amcrest.get("names") or self.list_from_env("AMCREST_NAMES"))
        sources = list[str](webrtc.get("sources") or self.list_from_env("AMCREST_SOURCES"))

        amcrest = {
            "hosts":                    hosts,
            "names":                    names,
            "port":                     int(str(amcrest.get("port") or os.getenv("AMCREST_PORT", 80))),
            "username":                     str(amcrest.get("username") or os.getenv("AMCREST_USERNAME", "")),
            "password":                     str(amcrest.get("password") or os.getenv("AMCREST_PASSWORD", "")),
            "storage_update_interval":  int(str(amcrest.get("storage_update_interval") or os.getenv("AMCREST_STORAGE_UPDATE_INTERVAL", 900))),
            "snapshot_update_interval": int(str(amcrest.get("snapshot_update_interval") or os.getenv("AMCREST_SNAPSHOT_UPDATE_INTERVAL", 60))),
            "webrtc": {
                "host":      str(webrtc.get("host") or os.getenv("AMCREST_WEBRTC_HOST", "")),
                "port":  int(str(webrtc.get("port") or os.getenv("AMCREST_WEBRTC_PORT", 1984))),
                "link":      str(webrtc.get("link") or os.getenv("AMCREST_WEBRTC_LINK", "webrtc")),
                "sources":   sources,
            },
        }

        config = {
            "mqtt":        mqtt,
            "amcrest":     amcrest,
            "debug":       bool(config.get("debug", os.getenv("DEBUG", "").lower() == "true")),
            "hide_ts":     bool(config.get("hide_ts", os.getenv("HIDE_TS", "").lower() == "true")),
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
        recording = await self.get_recorded_file(device_id, amcrest_file, encode=False)
        if recording:
            name = self.get_device_name_slug(device_id)
            time = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = self.config["media"]["path"]
            file_name = f"{name}-{time}.mp4"
            file_path = Path(f"{path}/{file_name}")

            # last chance to skip the recording
            if self.b_to_mb(len(recording)) > self.config["media"]["max_size"]:
                self.logger.info(f"skipping saving recording to {path} because {self.b_to_mb(len(recording))} > {self.config["media"]["max_size"]} MB")
                return None

            try:
                file_path.write_bytes(recording.encode("latin-1"))
            except PermissionError as err:
                self.logger.error(f"permission error saving recording to {file_path}: {err!r}")
                return None
            except IOError as err:
                self.logger.error(f"failed to save recording to {file_path}: {err!r}")
                return None
            except Exception as err:
                self.logger.error(f"failed to save recording to {file_path}: {err!r}")
                return None

            self.upsert_state(
                device_id,
                media={"recording": str(file_path)},
                sensor={"recording_time": datetime.now(timezone.utc).isoformat()},
            )
            local_file = Path(f"./{file_name}")
            latest_link = Path(f"{path}/{name}-latest.mp4")

            try:
                if latest_link.is_symlink():
                    latest_link.unlink()
                latest_link.symlink_to(local_file)
            except IOError as err:
                self.logger.error(f"failed to save symlink {latest_link} -> {local_file}: {err!r}")
                pass

            if "media_source" in self.config["media"]:
                url = f"{self.config["media"]["media_source"]}/{file_name}"
                self.upsert_state(device_id, sensor={"recording_url": url})
                return url

            self.upsert_state(
                device_id,
                media={"recording": file_path},
                sensor={"recording_time": datetime.now(timezone.utc).isoformat()},
            )

            # update symlink to "lastest" recording
            local_file = Path(f"./{file_name}")
            latest_link = Path(f"{path}/{name}-latest.mp4")
            if latest_link.is_symlink():
                latest_link.unlink()
            latest_link.symlink_to(local_file)

            if "media_source" in self.config["media"]:
                url = f"{self.config["media"]["media_source"]}/{file_name}"
                self.upsert_state(device_id, sensor={"recording_url": url})
                return url
        return None

    def handle_signal(self: Amcrest2Mqtt, signum: int, _: FrameType | None) -> Any:
        sig_name = signal.Signals(signum).name
        self.logger.warning(f"{sig_name} received - stopping service loop")
        self.running = False

        def _force_exit() -> None:
            self.logger.warning("force-exiting process after signal")
            os._exit(0)

        threading.Timer(5.0, _force_exit).start()

    # Device properties --------------------------------------------------------------------------

    def get_device_name(self: Amcrest2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"]["device"]["name"])

    def get_device_name_slug(self: Amcrest2Mqtt, device_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", self.get_device_name(device_id).lower())

    def get_component(self: Amcrest2Mqtt, device_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id]["component"])

    def get_platform(self: Amcrest2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"].get("platform", "unknown"))

    def is_discovered(self: Amcrest2Mqtt, device_id: str) -> bool:
        return cast(bool, self.states[device_id]["internal"].get("discovered", False))

    def get_device_state_topic(self: Amcrest2Mqtt, device_id: str, mode_name: str = "") -> str:
        component = self.get_component(device_id)["cmps"][f"{device_id}_{mode_name}"] if mode_name else self.get_component(device_id)

        match component["platform"]:
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

    # Upsert devices and states -------------------------------------------------------------------

    def assert_no_tuples(self: Amcrest2Mqtt, data: Any, path: str = "root") -> None:
        if isinstance(data, tuple):
            raise TypeError(f"⚠️ Found tuple at {path}: {data!r}")

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, tuple):
                    raise TypeError(f"⚠️ Found tuple key at {path}: {key!r}")
                self.assert_no_tuples(value, f"{path}.{key}")
        elif isinstance(data, list):
            for idx, value in enumerate(data):
                self.assert_no_tuples(value, f"{path}[{idx}]")

    def upsert_device(self: Amcrest2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> bool:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],
            ["override"],
        )
        prev = self.devices.get(device_id, {})
        for section, data in kwargs.items():
            # Pre-merge check
            self.assert_no_tuples(data, f"device[{device_id}].{section}")
            merged = MERGER.merge(self.devices.get(device_id, {}), {section: data})
            # Post-merge check
            self.assert_no_tuples(merged, f"device[{device_id}].{section} (post-merge)")
            self.devices[device_id] = merged
        new = self.devices.get(device_id, {})
        return False if prev == new else True

    def upsert_state(self: Amcrest2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> bool:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],
            ["override"],
        )
        prev = self.states.get(device_id, {})
        for section, data in kwargs.items():
            self.assert_no_tuples(data, f"state[{device_id}].{section}")
            merged = MERGER.merge(self.states.get(device_id, {}), {section: data})
            self.assert_no_tuples(merged, f"state[{device_id}].{section} (post-merge)")
            self.states[device_id] = merged
        new = self.states.get(device_id, {})
        return False if prev == new else True
