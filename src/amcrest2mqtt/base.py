# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from json_logging import get_logger
from mqtt_helper import MqttHelper
from paho.mqtt.client import Client

from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class Base:
    def __init__(self: Amcrest2Mqtt, args: argparse.Namespace | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        self.loop = asyncio.get_running_loop()
        self.loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=16))

        self.args = args
        self.logger = get_logger(__name__)

        # now load self.config right away
        cfg_arg = getattr(args, "config", None)
        self.config = self.load_config(cfg_arg)

        if not self.config["mqtt"] or not self.config["amcrest"]:
            raise ValueError("config was not loaded")

        # down in trenches if we have to
        if self.config.get("debug"):
            self.logger.setLevel(logging.DEBUG)

        self.mqtt_config = self.config["mqtt"]
        self.amcrest_config = self.config["amcrest"]

        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"
        self.qos = self.mqtt_config["qos"]

        self.mqtt_helper = MqttHelper(self.service, default_qos=self.qos, default_retain=True)

        self.running = False
        self.discovery_complete = False

        self.devices: dict[str, Any] = {}
        self.states: dict[str, Any] = {}
        self.dirty: dict[str, set[tuple[str, str]]] = {}
        self.amcrest_devices: dict[str, Any] = {}
        self.events: list[str] = []

        self.mqttc: Client
        self.mqtt_connect_time: datetime
        self.client_id = self.mqtt_helper.client_id()

        self.storage_update_interval = self.amcrest_config.get("storage_update_interval", 15)
        self.snapshot_update_interval = self.config["amcrest"].get("snapshot_update_interval", 60)

        self.device_interval = self.config["amcrest"].get("device_interval", 30)
        self.device_list_interval = self.config["amcrest"].get("device_list_interval", 300)

        self.api_calls = 0
        self.last_call_date = datetime.now(UTC).astimezone()
        self.rate_limited = False

    async def __aenter__(self: Self) -> Amcrest2Mqtt:
        super_enter = getattr(super(), "__enter__", None)
        if callable(super_enter):
            super_enter()

        await cast(Any, self).mqttc_create()
        cast(Any, self).restore_state()
        self.running = True

        return cast(Amcrest2Mqtt, self)

    async def __aexit__(self: Self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        super_exit = getattr(super(), "__exit__", None)
        if callable(super_exit):
            super_exit(exc_type, exc_val, exc_tb)

        self.running = False
        cast(Any, self).save_state()

        if cast(Any, self).mqttc is not None:
            try:
                await cast(Any, self).publish_service_availability("offline")
                cast(Any, self).mqttc.loop_stop()
            except Exception as err:  # noqa: BLE001 - best-effort cleanup; shutdown must not be blocked by a broker error
                self.logger.debug(f"mqtt loop_stop failed: {err!r}")

            if cast(Any, self).mqttc.is_connected():
                try:
                    cast(Any, self).mqttc.disconnect()
                    self.logger.info("disconnected from MQTT broker")
                except Exception as err:  # noqa: BLE001 - best-effort cleanup; shutdown must not be blocked by a broker error
                    self.logger.warning(f"error during MQTT disconnect: {err!r}")

        self.logger.info("exiting gracefully")

    def save_state(self: Amcrest2Mqtt) -> None:
        data_file = Path(self.config["config_path"]) / "amcrest2mqtt.dat"
        state = {
            "api_calls": self.api_calls,
            "last_call_date": str(self.last_call_date),
        }
        # Write to a temp file alongside the target and rename over it. os.replace is atomic, so a
        # failure can never leave a truncated .dat behind — the previous version did exactly that:
        # O_TRUNC emptied the file, then os.fchmod raised EPERM on a volume that does not permit
        # chmod, and the write never happened.
        #
        # mkstemp rather than a fixed "<name>.tmp": it creates a fresh file with O_EXCL and mode
        # 0600, so a stale temp left by an earlier crash cannot have its looser permissions
        # inherited, and a symlink planted at a predictable path cannot be followed and truncated.
        tmp_path = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(data_file.parent), prefix=f".{data_file.name}.", suffix=".tmp")
            tmp_path = Path(tmp_name)
            # mkstemp hands back a raw descriptor. os.fdopen takes ownership only once it
            # succeeds, so close it by hand if it does not -- otherwise the fd leaks.
            try:
                file = os.fdopen(fd, "w", encoding="utf-8")
            except BaseException:
                # best-effort: a failure to close must not replace the fdopen error that
                # actually explains what went wrong, since the caller logs whatever propagates
                with suppress(OSError):
                    os.close(fd)
                raise
            with file:
                json.dump(state, file, indent=4)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, data_file)
            self.logger.info(f"saved state to {data_file}")
        except OSError as err:
            self.logger.error(f"could not save state to {data_file}: {err!r}")
            if tmp_path is not None:
                with suppress(OSError):
                    os.unlink(tmp_path)

    def restore_state(self: Amcrest2Mqtt) -> None:
        data_file = Path(self.config["config_path"]) / "amcrest2mqtt.dat"
        if os.path.exists(data_file):
            try:
                with open(data_file, "r", encoding="utf-8") as file:
                    state = json.loads(file.read())
                    self.api_calls = state["api_calls"]
                    restored = datetime.fromisoformat(state["last_call_date"])
                    if restored.tzinfo is None:
                        # state written before timestamps were timezone-aware: it is local wall-clock
                        restored = restored.astimezone()
                    self.last_call_date = restored
                    self.logger.info(f"restored state from {data_file}: {self.api_calls} / {self.last_call_date!s}")
            except (ValueError, KeyError, TypeError, OSError) as err:
                self.logger.warning(f"could not restore state from {data_file}: {err} — starting fresh")
