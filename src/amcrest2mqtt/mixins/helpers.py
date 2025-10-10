# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from deepmerge import Merger
import os
import signal
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amcrest2mqtt.core import Amcrest2Mqtt
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class HelpersMixin:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

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
                "last_update": self.get_last_update(device_id),
            },
        )

    # send command to Amcrest -----------------------------------------------------------------------

    def send_command(self: Amcrest2Mqtt, device_id, response):
        return

    def handle_service_message(self: Amcrest2Mqtt, handler, message):
        match handler:
            case "storage_refresh":
                self.device_interval = message
            case "device_list_refresh":
                self.device_list_interval = message
            case "snapshot_refresh":
                self.device_boost_interval = message
            case "refresh_device_list":
                if message == "refresh":
                    self.rediscover_all()
                else:
                    self.logger.error("[handler] unknown [message]")
                    return
            case _:
                self.logger.error(f"Unrecognized message to {self.service_slug}: {handler} -> {message}")
                return
        self.publish_service_state()

    def rediscover_all(self: Amcrest2Mqtt):
        self.publish_service_state()
        self.publish_service_discovery()
        for device_id in self.devices:
            if device_id == "service":
                continue
            self.publish_device_state(device_id)
            self.publish_device_discovery(device_id)

    # Utility functions ---------------------------------------------------------------------------

    def _handle_signal(self: Amcrest2Mqtt, signum, frame=None):
        """Handle SIGTERM/SIGINT and exit cleanly or forcefully."""
        sig_name = signal.Signals(signum).name
        self.logger.warning(f"{sig_name} received - stopping service loop")
        self.running = False

        def _force_exit():
            self.logger.warning("Force-exiting process after signal")
            os._exit(0)

        threading.Timer(5.0, _force_exit).start()

    # Upsert devices and states -------------------------------------------------------------------

    MERGER = Merger(
        [(dict, "merge"), (list, "append_unique"), (set, "union")],
        ["override"],  # type conflicts: new wins
        ["override"],  # fallback
    )

    def _assert_no_tuples(self: Amcrest2Mqtt, data, path="root"):
        """Recursively check for tuples in both keys and values of dicts/lists."""
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

    def upsert_device(self: Amcrest2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool) -> None:
        for section, data in kwargs.items():
            # Pre-merge check
            self._assert_no_tuples(data, f"device[{device_id}].{section}")
            merged = self.MERGER.merge(self.devices.get(device_id, {}), {section: data})
            # Post-merge check
            self._assert_no_tuples(merged, f"device[{device_id}].{section} (post-merge)")
            self.devices[device_id] = merged

    def upsert_state(self: Amcrest2Mqtt, device_id, **kwargs: dict[str, Any] | str | int | bool) -> None:
        for section, data in kwargs.items():
            self._assert_no_tuples(data, f"state[{device_id}].{section}")
            merged = self.MERGER.merge(self.states.get(device_id, {}), {section: data})
            self._assert_no_tuples(merged, f"state[{device_id}].{section} (post-merge)")
            self.states[device_id] = merged
