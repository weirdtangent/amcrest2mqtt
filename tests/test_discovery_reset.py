# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
"""Tests for clearing/rebuilding HA discovery when the entity layout changes."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from amcrest2mqtt.mixins.helpers import HelpersMixin
from amcrest2mqtt.mixins.mqtt import MqttMixin
from amcrest2mqtt.mixins.publish import PublishMixin


class FakeService(HelpersMixin, PublishMixin, MqttMixin):
    def __init__(self, devices=None):
        self.logger = MagicMock()
        self.mqtt_config = {"discovery_prefix": "homeassistant"}
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.service_slug = "amcrest2mqtt"
        self.mqtt_helper.disc_t = MagicMock(side_effect=lambda kind, did: f"homeassistant/{kind}/amcrest2mqtt_{did}/config")
        self.devices = {d: {"component": {}} for d in (devices or [])}
        self.states = {d: {"internal": {"discovered": True}} for d in (devices or [])}
        self.dirty = {}
        self.publish_service_state = AsyncMock()

    def upsert_state(self, device_id, **kwargs):
        for section, values in kwargs.items():
            self.states.setdefault(device_id, {}).setdefault(section, {}).update(values)
        return True


def _cleared_topics(svc):
    return [call.args[0] for call in svc.mqtt_helper.safe_publish.call_args_list if call.args[1] == ""]


class TestClearDiscovery:
    @pytest.mark.asyncio
    async def test_delegates_to_the_broker_sweep(self):
        """The device map is empty at connect time, so the topic list must come from the broker."""
        svc = FakeService()
        svc.clear_retained_discovery = AsyncMock()

        await svc.clear_discovery()

        svc.clear_retained_discovery.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clears_topics_the_device_map_never_knew_about(self):
        svc = FakeService()  # no devices loaded yet, exactly as at mqtt_on_connect
        svc.collect_retained_discovery_topics = AsyncMock(
            return_value=[
                "homeassistant/device/amcrest2mqtt_AMC001/config",
                "homeassistant/device/amcrest2mqtt_service/config",
            ]
        )

        await svc.clear_discovery()

        assert _cleared_topics(svc) == [
            "homeassistant/device/amcrest2mqtt_AMC001/config",
            "homeassistant/device/amcrest2mqtt_service/config",
        ]

    @pytest.mark.asyncio
    async def test_clears_with_empty_payload_retained(self):
        """An empty payload removes the registry entry; None would publish the string "null"."""
        svc = FakeService()
        svc.collect_retained_discovery_topics = AsyncMock(return_value=["homeassistant/device/amcrest2mqtt_service/config"])

        await svc.clear_discovery()

        for call in svc.mqtt_helper.safe_publish.call_args_list:
            assert call.args[1] == ""
            assert call.kwargs == {"retain": True}

    @pytest.mark.asyncio
    async def test_marks_loaded_devices_undiscovered(self):
        """Matters on the manual reset path, where devices are loaded by the time it runs."""
        svc = FakeService(devices=["AMC001"])
        svc.clear_retained_discovery = AsyncMock()

        await svc.clear_discovery()

        assert svc.states["AMC001"]["internal"]["discovered"] is False


class TestResetDiscoveryCommand:
    @pytest.mark.asyncio
    async def test_reset_discovery_survives_the_non_numeric_path(self):
        """It must be handled before the int() that every other service command relies on."""
        svc = FakeService()
        svc.reset_discovery = AsyncMock()

        await svc.handle_service_command("reset_discovery", "PRESS")

        svc.reset_discovery.assert_awaited_once()
        svc.logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_numeric_commands_still_work(self):
        svc = FakeService()

        await svc.handle_service_command("refresh_interval", "45")

        assert svc.device_interval == 45
        svc.publish_service_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_numeric_value_for_a_numeric_command_still_rejected(self):
        svc = FakeService()
        svc.reset_discovery = AsyncMock()

        await svc.handle_service_command("refresh_interval", "soon")

        svc.logger.warning.assert_called_once()
        svc.reset_discovery.assert_not_awaited()


class TestSchemaVersion:
    def test_service_declares_a_schema_version(self):
        assert MqttMixin.DISCOVERY_SCHEMA_VERSION >= 1

    def test_version_topic_is_outside_the_command_wildcard(self):
        """`<slug>/service/+/set` must not swallow the version topic."""
        svc = FakeService()

        topic = svc.discovery_schema_version_topic()

        assert topic == "amcrest2mqtt/service/discovery_schema_version"
        assert not topic.endswith("/set")
        assert len(topic.split("/")) == 3
