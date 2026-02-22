# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import pytest
from unittest.mock import MagicMock, patch

from amcrest2mqtt.mixins.publish import PublishMixin
from amcrest2mqtt.mixins.helpers import HelpersMixin


class FakePublisher(HelpersMixin, PublishMixin):
    def __init__(self):
        self.service = "amcrest2mqtt"
        self.service_name = "amcrest2mqtt service"
        self.qos = 0
        self.config = {"version": "v0.1.0-test"}
        self.logger = MagicMock()
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.safe_publish = MagicMock()
        self.mqtt_helper.service_slug = "amcrest2mqtt"
        self.mqtt_helper.svc_unique_id = MagicMock(side_effect=lambda e: f"amcrest2mqtt_{e}")
        self.mqtt_helper.dev_unique_id = MagicMock(side_effect=lambda d, e: f"amcrest2mqtt_{d}_{e}")
        self.mqtt_helper.device_slug = MagicMock(side_effect=lambda d: f"amcrest2mqtt_{d}")
        self.mqtt_helper.stat_t = MagicMock(side_effect=lambda *args: "/".join(["amcrest2mqtt"] + list(args)))
        self.mqtt_helper.avty_t = MagicMock(side_effect=lambda *args: "/".join(["amcrest2mqtt"] + list(args) + ["availability"]))
        self.mqtt_helper.cmd_t = MagicMock(side_effect=lambda *args: "/".join(["amcrest2mqtt"] + list(args) + ["set"]))
        self.mqtt_helper.disc_t = MagicMock(side_effect=lambda kind, did: f"homeassistant/{kind}/amcrest2mqtt_{did}/config")
        self.devices = {}
        self.states = {}


async def _fake_to_thread(fn, *args):
    """Replace asyncio.to_thread with synchronous call for testing."""
    return fn(*args)


class TestServiceDiscovery:
    @pytest.mark.asyncio
    async def test_publishes_service_discovery(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        pub.mqtt_helper.safe_publish.assert_called()
        topic = pub.mqtt_helper.safe_publish.call_args_list[0].args[0]
        payload = json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])

        assert topic == "homeassistant/device/amcrest2mqtt_service/config"
        assert payload["device"]["name"] == "amcrest2mqtt service"
        assert "cmps" in payload
        assert len(payload["cmps"]) == 7
        assert "server" in payload["cmps"]
        assert "api_calls" in payload["cmps"]
        assert "rate_limited" in payload["cmps"]
        assert "last_call" in payload["cmps"]
        assert "refresh_interval" in payload["cmps"]
        assert "storage_interval" in payload["cmps"]
        assert "snapshot_interval" in payload["cmps"]

    @pytest.mark.asyncio
    async def test_service_discovery_marks_discovered(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        assert pub.states["service"]["internal"]["discovered"] is True

    @pytest.mark.asyncio
    async def test_service_discovery_payload_structure(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        payload = json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])
        assert payload["cmps"]["server"]["p"] == "binary_sensor"
        assert payload["cmps"]["server"]["device_class"] == "connectivity"
        assert payload["cmps"]["api_calls"]["p"] == "sensor"
        assert payload["cmps"]["rate_limited"]["p"] == "binary_sensor"


class TestServiceAvailability:
    @pytest.mark.asyncio
    async def test_publishes_online(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_availability("online")

        pub.mqtt_helper.safe_publish.assert_called_once()
        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "online"

    @pytest.mark.asyncio
    async def test_publishes_offline(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_availability("offline")

        pub.mqtt_helper.safe_publish.assert_called_once()
        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "offline"


class TestServiceState:
    @pytest.mark.asyncio
    async def test_publishes_all_service_metrics(self):
        from datetime import datetime

        pub = FakePublisher()
        pub.api_calls = 42
        pub.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        pub.rate_limited = False
        pub.device_interval = 30
        pub.storage_update_interval = 900
        pub.snapshot_update_interval = 60

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_state()

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert any("server" in t for t in topics)
        assert any("api_calls" in t for t in topics)
        assert any("last_call" in t for t in topics)
        assert any("rate_limited" in t for t in topics)

    @pytest.mark.asyncio
    async def test_last_call_published_as_utc(self):
        from datetime import datetime

        pub = FakePublisher()
        pub.api_calls = 0
        pub.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        pub.rate_limited = False
        pub.device_interval = 30
        pub.storage_update_interval = 900
        pub.snapshot_update_interval = 60

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_state()

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "last_call" in c.args[0]:
                # should be ISO format with timezone info
                assert "T" in str(c.args[1])
                break
        else:
            pytest.fail("last_call topic not published")

    @pytest.mark.asyncio
    async def test_rate_limited_yes_no(self):
        from datetime import datetime

        pub = FakePublisher()
        pub.api_calls = 0
        pub.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        pub.rate_limited = True
        pub.device_interval = 30
        pub.storage_update_interval = 900
        pub.snapshot_update_interval = 60

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_state()

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "rate_limited" in c.args[0]:
                assert c.args[1] == "YES"
                break
        else:
            pytest.fail("rate_limited topic not published")


class TestDeviceDiscovery:
    @pytest.mark.asyncio
    async def test_publishes_device_discovery(self):
        pub = FakePublisher()
        pub.devices["CAM001"] = {
            "component": {
                "device": {"name": "Front Yard"},
                "cmps": {"camera": {"p": "camera"}},
            }
        }
        pub.states["CAM001"] = {}

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_discovery("CAM001")

        topic = pub.mqtt_helper.safe_publish.call_args.args[0]
        assert topic == "homeassistant/device/amcrest2mqtt_CAM001/config"

    @pytest.mark.asyncio
    async def test_device_discovery_marks_discovered(self):
        pub = FakePublisher()
        pub.devices["CAM001"] = {"component": {"device": {"name": "Front Yard"}}}
        pub.states["CAM001"] = {}

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_discovery("CAM001")

        assert pub.states["CAM001"]["internal"]["discovered"] is True


class TestDeviceAvailability:
    @pytest.mark.asyncio
    async def test_publishes_online(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_availability("CAM001", online=True)

        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "online"

    @pytest.mark.asyncio
    async def test_publishes_offline(self):
        pub = FakePublisher()

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_availability("CAM001", online=False)

        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "offline"


class TestDeviceState:
    @pytest.mark.asyncio
    async def test_publishes_nested_dict_states(self):
        pub = FakePublisher()
        pub.states["CAM001"] = {
            "switch": {"privacy": "OFF", "motion_detection": "ON"},
            "sensor": {"storage_used": "50.2"},
        }

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("CAM001")

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert any("switch" in t and "privacy" in t for t in topics)
        assert any("switch" in t and "motion_detection" in t for t in topics)
        assert any("sensor" in t and "storage_used" in t for t in topics)

    @pytest.mark.asyncio
    async def test_subject_filter(self):
        pub = FakePublisher()
        pub.states["CAM001"] = {
            "switch": {"privacy": "OFF"},
            "sensor": {"storage_used": "50.2"},
        }

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("CAM001", subject="switch")

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert any("switch" in t for t in topics)
        assert not any("sensor" in t for t in topics)

    @pytest.mark.asyncio
    async def test_sub_filter(self):
        pub = FakePublisher()
        pub.states["CAM001"] = {
            "switch": {"privacy": "OFF", "motion_detection": "ON"},
        }

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("CAM001", subject="switch", sub="privacy")

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert len(topics) == 1
        assert "privacy" in topics[0]

    @pytest.mark.asyncio
    async def test_bool_and_list_encoded_as_json(self):
        pub = FakePublisher()
        pub.states["CAM001"] = {
            "test": {"flag": True, "items": [1, 2, 3]},
        }

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("CAM001")

        payloads = {c.args[0]: c.args[1] for c in pub.mqtt_helper.safe_publish.call_args_list}
        for topic, value in payloads.items():
            if "flag" in topic:
                assert value == json.dumps(True)
            if "items" in topic:
                assert value == json.dumps([1, 2, 3])

    @pytest.mark.asyncio
    async def test_attributes_published_as_json_object(self):
        pub = FakePublisher()
        pub.states["CAM001"] = {
            "attributes": {"firmware": "v1.0", "model": "IP8M"},
        }

        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("CAM001")

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "attributes" in c.args[0]:
                payload = json.loads(c.args[1])
                assert payload["firmware"] == "v1.0"
                assert payload["model"] == "IP8M"
                break
        else:
            pytest.fail("attributes topic not published")
