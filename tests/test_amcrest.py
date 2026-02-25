# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from unittest.mock import MagicMock

from amcrest2mqtt.mixins.amcrest import AmcrestMixin
from amcrest2mqtt.mixins.amcrest_api import AmcrestAPIMixin


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

    def test_ad110_returns_doorbell(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "AD110"}
        assert amcrest.classify_device(device) == "doorbell"

    def test_ad410_returns_doorbell(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "AD410"}
        assert amcrest.classify_device(device) == "doorbell"

    def test_case_insensitive_matching(self):
        amcrest = FakeAmcrest()
        # classify_device uppercases device_type before matching
        device = {"device_type": "ip2m-841b"}
        assert amcrest.classify_device(device) == "camera"

    def test_ad110_sh_variant_returns_doorbell(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "AD110-SH"}
        assert amcrest.classify_device(device) == "doorbell"

    def test_doorbell_case_insensitive(self):
        amcrest = FakeAmcrest()
        device = {"device_type": "ad410"}
        assert amcrest.classify_device(device) == "doorbell"


class FakeEventProcessor(AmcrestAPIMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.devices = {}
        self.states = {}
        self.events = []
        self.amcrest_devices = {}

    def get_device_name(self, device_id):
        return self.devices.get(device_id, {}).get("name", device_id)

    def _add_device(self, device_id, is_ad110=False, is_ad410=False):
        self.amcrest_devices[device_id] = {
            "camera": MagicMock(),
            "config": {
                "is_ad110": is_ad110,
                "is_ad410": is_ad410,
                "is_doorbell": is_ad110 or is_ad410,
            },
        }
        self.devices[device_id] = {"name": "Test Device"}
        self.states[device_id] = {}


class TestProcessDeviceEvent:
    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_alarm_local_ad410_start_creates_doorbell_on(self):
        ep = FakeEventProcessor()
        ep._add_device("DB001", is_ad410=True)
        payload = {"action": "Start", "data": {}}
        self._run(ep.process_device_event("DB001", "AlarmLocal", payload))
        assert len(ep.events) == 1
        assert ep.events[0]["event"] == "doorbell"
        assert ep.events[0]["payload"] == "on"

    def test_alarm_local_ad410_stop_creates_doorbell_off(self):
        ep = FakeEventProcessor()
        ep._add_device("DB001", is_ad410=True)
        payload = {"action": "Stop", "data": {}}
        self._run(ep.process_device_event("DB001", "AlarmLocal", payload))
        assert len(ep.events) == 1
        assert ep.events[0]["event"] == "doorbell"
        assert ep.events[0]["payload"] == "off"

    def test_alarm_local_ignored_for_non_ad410(self):
        ep = FakeEventProcessor()
        ep._add_device("CAM001")
        payload = {"action": "Start", "data": {}}
        self._run(ep.process_device_event("CAM001", "AlarmLocal", payload))
        # should fall through to generic event, not doorbell
        assert len(ep.events) == 1
        assert ep.events[0]["event"] == "AlarmLocal"

    def test_do_talk_action_creates_doorbell_event_for_ad110(self):
        ep = FakeEventProcessor()
        ep._add_device("DB001", is_ad110=True)
        payload = {"action": "Start", "data": {"Action": "Invite"}}
        self._run(ep.process_device_event("DB001", "_DoTalkAction_", payload))
        assert len(ep.events) == 1
        assert ep.events[0]["event"] == "doorbell"
        assert ep.events[0]["payload"] == "on"

    def test_do_talk_action_ignored_for_ad410(self):
        ep = FakeEventProcessor()
        ep._add_device("DB001", is_ad410=True)
        payload = {"action": "Start", "data": {"Action": "Invite"}}
        self._run(ep.process_device_event("DB001", "_DoTalkAction_", payload))
        # AD410 uses AlarmLocal for doorbell, _DoTalkAction_ should be ignored
        assert all(e["event"] != "doorbell" for e in ep.events)
