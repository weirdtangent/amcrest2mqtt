# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from mqtt_helper import parse_device_topic
from amcrest2mqtt.mixins.mqtt import MqttMixin


class FakeMqtt(MqttMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.mqtt_config = {"discovery_prefix": "homeassistant"}
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.service_slug = "amcrest2mqtt"
        self.devices = {}
        self.states = {}


def _make_msg(topic, payload):
    """Create a fake MQTTMessage with the given topic and payload."""
    msg = MagicMock()
    msg.topic = topic
    if isinstance(payload, dict):
        msg.payload = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        msg.payload = payload.encode("utf-8")
    else:
        msg.payload = payload
    return msg


class TestMqttSubscriptionTopics:
    def test_returns_expected_topics(self):
        mqtt = FakeMqtt()
        topics = mqtt.mqtt_subscription_topics()

        assert "homeassistant/status" in topics
        assert f"{mqtt.mqtt_helper.service_slug}/service/+/set" in topics
        assert f"{mqtt.mqtt_helper.service_slug}/service/+/command" in topics
        assert f"{mqtt.mqtt_helper.service_slug}/+/switch/+/set" in topics
        assert f"{mqtt.mqtt_helper.service_slug}/+/button/+/set" in topics

    def test_returns_list(self):
        mqtt = FakeMqtt()
        topics = mqtt.mqtt_subscription_topics()
        assert isinstance(topics, list)
        assert len(topics) == 5


class TestMqttOnMessage:
    @pytest.mark.asyncio
    async def test_ha_online_triggers_handle_homeassistant_message(self):
        mqtt = FakeMqtt()
        mqtt.handle_homeassistant_message = AsyncMock()
        mqtt.handle_service_command = AsyncMock()
        mqtt.handle_device_topic = AsyncMock()
        mqtt.handle_device_command = AsyncMock()

        msg = _make_msg("homeassistant/status", "online")
        await mqtt.mqtt_on_message(None, None, msg)

        mqtt.handle_homeassistant_message.assert_awaited_once_with("online")
        mqtt.handle_service_command.assert_not_awaited()
        mqtt.handle_device_topic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_device_topic_routes_to_handle_device_topic(self):
        mqtt = FakeMqtt()
        mqtt.handle_homeassistant_message = AsyncMock()
        mqtt.handle_service_command = AsyncMock()
        mqtt.handle_device_topic = AsyncMock()
        mqtt.handle_device_command = AsyncMock()

        msg = _make_msg("amcrest2mqtt/amcrest2mqtt_SERIAL123/switch/privacy/set", "ON")
        await mqtt.mqtt_on_message(None, None, msg)

        mqtt.handle_homeassistant_message.assert_not_awaited()
        mqtt.handle_service_command.assert_not_awaited()
        mqtt.handle_device_topic.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_service_command_routes_correctly(self):
        mqtt = FakeMqtt()
        mqtt.handle_homeassistant_message = AsyncMock()
        mqtt.handle_service_command = AsyncMock()
        mqtt.handle_device_topic = AsyncMock()
        mqtt.handle_device_command = AsyncMock()

        msg = _make_msg("amcrest2mqtt/service/storage_interval/set", "600")
        await mqtt.mqtt_on_message(None, None, msg)

        # "600" is valid JSON so it gets decoded to int 600
        mqtt.handle_service_command.assert_awaited_once_with("storage_interval", 600)
        mqtt.handle_homeassistant_message.assert_not_awaited()
        mqtt.handle_device_topic.assert_not_awaited()


class TestParseDeviceTopic:
    def test_parses_valid_switch_topic(self):
        components = "amcrest2mqtt/amcrest2mqtt_SERIAL123/switch/privacy/set".split("/")
        result = parse_device_topic(components)

        assert result == ("amcrest2mqtt", "SERIAL123", "privacy")

    def test_non_set_suffix_returns_none(self):
        components = "amcrest2mqtt/amcrest2mqtt_SERIAL123/switch/privacy/get".split("/")
        result = parse_device_topic(components)

        assert result is None

    def test_malformed_topic_returns_none(self):
        # Topic with no underscore in second component will raise in split("_", 1)
        components = ["amcrest2mqtt", "malformed", "switch", "privacy", "set"]
        result = parse_device_topic(components)

        assert result is None


class TestHandleHomeassistantMessage:
    @pytest.mark.asyncio
    async def test_online_calls_rediscover_all(self):
        mqtt = FakeMqtt()
        mqtt.rediscover_all = AsyncMock()

        await mqtt.handle_homeassistant_message("online")

        mqtt.rediscover_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_offline_does_nothing(self):
        mqtt = FakeMqtt()
        mqtt.rediscover_all = AsyncMock()

        await mqtt.handle_homeassistant_message("offline")

        mqtt.rediscover_all.assert_not_awaited()
