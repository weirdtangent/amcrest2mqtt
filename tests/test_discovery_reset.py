# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
"""Tests for clearing/rebuilding HA discovery when the entity layout changes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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


class TestStableObjectIds:
    """entity_id must be pinned to the component key, never the display name.

    HA derives entity_id from the display name at first discovery and keeps it forever, keyed on
    unique_id — which is how storage_interval came to own number.amcrest2mqtt_service_refresh_interval
    on a live install. Publishing the default entity_id closes that off at the only point it can be
    closed.

    HA Core 2026.4 removed `object_id`; `default_entity_id` (`def_ent_id`) replaced it and wants a
    full entity_id. A payload still publishing `obj_id` is ignored outright, which puts newly
    discovered entities straight back into the display-name failure above.
    """

    async def _publish_service(self):
        import json
        from unittest.mock import patch

        from tests.test_publish import FakePublisher, _fake_to_thread

        pub = FakePublisher()
        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        return json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])["cmps"]

    @pytest.mark.asyncio
    async def test_every_service_component_publishes_a_def_ent_id(self):
        cmps = await self._publish_service()

        missing = [k for k, c in cmps.items() if "def_ent_id" not in c]
        assert missing == [], f"components without def_ent_id: {missing}"

    @pytest.mark.asyncio
    async def test_no_component_still_publishes_the_removed_obj_id(self):
        """HA 2026.4+ does not recognise obj_id, so shipping one is dead weight and a false signal."""
        cmps = await self._publish_service()

        stale = [k for k, c in cmps.items() if "obj_id" in c]
        assert stale == [], f"components still publishing obj_id: {stale}"

    @pytest.mark.asyncio
    async def test_def_ent_id_follows_the_key_not_the_name(self):
        cmps = await self._publish_service()

        # 'server' is displayed as the service name, yet its id tracks the key — the exact
        # divergence that produced ..._amcrest2mqtt_service_2 in the wild
        assert cmps["server"]["def_ent_id"] == "binary_sensor.amcrest2mqtt_service_server"
        assert cmps["storage_interval"]["def_ent_id"] == "number.amcrest2mqtt_service_storage_interval"
        assert cmps["refresh_interval"]["def_ent_id"] == "number.amcrest2mqtt_service_refresh_interval"

    @pytest.mark.asyncio
    async def test_storage_interval_declares_seconds_matching_what_is_published(self):
        """3070ad5 moved this to minutes/max-60 without converting the value, so configs
        carrying seconds (900) were rejected by HA as out of range."""
        import json
        from unittest.mock import patch

        from tests.test_publish import FakePublisher, _fake_to_thread

        pub = FakePublisher()
        with patch("amcrest2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        storage = json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])["cmps"]["storage_interval"]
        assert storage["unit_of_measurement"] == "s"
        assert storage["max"] == 3600
