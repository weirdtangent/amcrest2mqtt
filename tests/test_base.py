# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from amcrest2mqtt.base import Base
from amcrest2mqtt.mixins.helpers import HelpersMixin


class FakeBase(HelpersMixin, Base):
    """Minimal class to test Base lifecycle without full mixin stack."""

    pass


class TestSaveState:
    def test_saves_json_structure(self, tmp_path):
        state_file = tmp_path / "amcrest2mqtt.dat"

        # Create a minimal mock that has all the attributes Base.save_state needs
        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.api_calls = 42
        obj.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        obj.logger = MagicMock()

        Base.save_state(obj)

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["api_calls"] == 42
        assert "2026-01-15" in data["last_call_date"]

    def test_handles_permission_error(self, tmp_path):
        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.api_calls = 0
        obj.last_call_date = datetime.now()
        obj.logger = MagicMock()

        # Should not raise - logs error instead
        with patch("builtins.open", side_effect=PermissionError("mocked")):
            Base.save_state(obj)
        obj.logger.error.assert_called_once()


class TestRestoreState:
    def test_restores_state_from_file(self, tmp_path):
        state_file = tmp_path / "amcrest2mqtt.dat"
        state_file.write_text(
            json.dumps(
                {
                    "api_calls": 99,
                    "last_call_date": "2026-01-15 10:30:00.000000",
                }
            )
        )

        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.logger = MagicMock()

        Base.restore_state(obj)

        assert obj.api_calls == 99
        assert isinstance(obj.last_call_date, datetime)
        assert obj.last_call_date.year == 2026

    def test_missing_file_is_noop(self, tmp_path):
        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.logger = MagicMock()

        # Should not raise
        Base.restore_state(obj)
        obj.logger.info.assert_not_called()

    def test_restore_uses_utf8_encoding(self, tmp_path):
        """Validate the encoding='utf-8' bug fix."""
        state_file = tmp_path / "amcrest2mqtt.dat"
        state_file.write_text(
            json.dumps(
                {
                    "api_calls": 1,
                    "last_call_date": "2026-01-15 10:30:00.000000",
                }
            ),
            encoding="utf-8",
        )

        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.logger = MagicMock()

        Base.restore_state(obj)
        assert obj.api_calls == 1


class TestContextManager:
    @pytest.mark.asyncio
    async def test_aenter_calls_mqttc_create_and_restore_state(self):
        obj = object.__new__(FakeBase)
        obj.logger = MagicMock()
        obj.mqttc_create = AsyncMock()
        obj.restore_state = MagicMock()
        obj.running = False

        await Base.__aenter__(obj)

        obj.mqttc_create.assert_called_once()
        obj.restore_state.assert_called_once()
        assert obj.running is True

    @pytest.mark.asyncio
    async def test_aexit_saves_state_and_disconnects(self):
        obj = object.__new__(FakeBase)
        obj.logger = MagicMock()
        obj.running = True
        obj.save_state = MagicMock()
        obj.publish_service_availability = AsyncMock()
        obj.mqttc = MagicMock()
        obj.mqttc.is_connected.return_value = True
        obj.mqttc.loop_stop = MagicMock()
        obj.mqttc.disconnect = MagicMock()

        await Base.__aexit__(obj, None, None, None)

        assert obj.running is False
        obj.save_state.assert_called_once()
        obj.publish_service_availability.assert_called_once_with("offline")
        obj.mqttc.disconnect.assert_called_once()
