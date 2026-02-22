# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from unittest.mock import MagicMock

from amcrest2mqtt.mixins.amcrest import AmcrestMixin


class FakeAmcrest(AmcrestMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.mqtt_helper = MagicMock()
        self.devices = {}
        self.states = {}


class TestClassifyDevice:
    def test_ip2m_841b_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IP2M-841B"}
        assert amcrest.classify_device(device) == "camera"

    def test_ip4m_1041b_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IP4M-1041B"}
        assert amcrest.classify_device(device) == "camera"

    def test_ip8m_2496e_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IP8M-2496E"}
        assert amcrest.classify_device(device) == "camera"

    def test_ip3m_941w_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IP3M-941W"}
        assert amcrest.classify_device(device) == "camera"

    def test_ip5m_1176eb_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IP5M-1176EB"}
        assert amcrest.classify_device(device) == "camera"

    def test_ipm_721_returns_camera(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "IPM-721S"}
        assert amcrest.classify_device(device) == "camera"

    def test_unsupported_model_returns_empty(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "UNKNOWN-MODEL"}
        assert amcrest.classify_device(device) == ""

    def test_unsupported_model_logs_error(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "UNKNOWN-MODEL"}
        amcrest.classify_device(device)
        amcrest.logger.error.assert_called_once()

    def test_case_insensitive_matching(self):
        amcrest = FakeAmcrest()
        # classify_device uppercases device_type before matching
        device = {"device_type": "ip2m-841b"}
        assert amcrest.classify_device(device) == "camera"
