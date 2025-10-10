# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import argparse
import logging
from json_logging import get_logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol


class Base:
    if TYPE_CHECKING:
        self: "AmcrestServiceProtocol"

    def __init__(self, *, args: argparse.Namespace | None = None, **kwargs):
        super().__init__(**kwargs)

        self.args = args
        self.logger = get_logger(__name__)

        # and quiet down some others
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
        logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
        logging.getLogger("amcrest.http").setLevel(logging.ERROR)
        logging.getLogger("amcrest.event").setLevel(logging.WARNING)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

        # now load self.config right away
        cfg_arg = getattr(args, "config", None)
        self.config = self.load_config(cfg_arg)

        if not self.config["mqtt"] or not self.config["amcrest"]:
            raise ValueError("config was not loaded")

        # down in trenches if we have to
        if self.config.get("debug"):
            self.logger.setLevel(logging.DEBUG)

        self.running = False
        self.discovery_complete = False

        self.mqtt_config = self.config["mqtt"]
        self.amcrest_config = self.config["amcrest"]

        self.devices = {}
        self.states = {}
        self.boosted = []
        self.amcrest_devices = {}
        self.events = []

        self.mqttc = None
        self.mqtt_connect_time = None
        self.client_id = self.get_new_client_id()

        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"
        self.service_slug = self.service

        self.qos = self.mqtt_config["qos"]

        self.storage_update_interval = self.config["amcrest"].get("storage_update_interval", 900)
        self.snapshot_update_interval = self.config["amcrest"].get("snapshot_update_interval", 300)

        self.device_interval = self.config["amcrest"].get("device_interval", 30)
        self.device_boost_interval = self.config["amcrest"].get("device_boost_interval", 5)
        self.device_list_interval = self.config["amcrest"].get("device_list_interval", 300)

        self.last_call_date = ""
        self.timezone = self.config["timezone"]

        self.count = len(self.amcrest_config["hosts"])

        self.api_calls = 0
        self.last_call_date = None
        self.rate_limited = False

    def __enter__(self):
        super_enter = getattr(super(), "__enter__", None)
        if callable(super_enter):
            super_enter()

        self.mqttc_create()
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        super_exit = getattr(super(), "__exit__", None)
        if callable(super_exit):
            super_exit(exc_type, exc_val, exc_tb)

        self.running = False

        if self.mqttc is not None:
            try:
                self.mqttc.loop_stop()
            except Exception as e:
                self.logger.debug(f"MQTT loop_stop failed: {e}")

            if self.mqttc.is_connected():
                try:
                    self.mqttc.disconnect()
                    self.logger.info("Disconnected from MQTT broker")
                except Exception as e:
                    self.logger.warning(f"Error during MQTT disconnect: {e}")

        self.logger.info("Exiting gracefully")
