# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import pytest


@pytest.fixture
def sample_amcrest_config():
    return {
        "mqtt": {
            "host": "10.10.10.1",
            "port": 1883,
            "qos": 0,
            "protocol_version": "5",
            "username": "mqtt_user",
            "password": "mqtt_pass",
            "tls_enabled": False,
            "prefix": "amcrest2mqtt",
            "discovery_prefix": "homeassistant",
        },
        "amcrest": {
            "hosts": ["192.168.1.100"],
            "names": ["Front Yard"],
            "port": 80,
            "username": "admin",
            "password": "secret",
            "storage_update_interval": 900,
            "snapshot_update_interval": 60,
            "webrtc": {
                "host": "192.168.1.50",
                "port": 1984,
                "link": "webrtc",
                "sources": ["front_yard"],
            },
        },
    }
