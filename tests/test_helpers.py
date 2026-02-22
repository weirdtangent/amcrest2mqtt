# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import os
import pytest
from unittest.mock import MagicMock

from amcrest2mqtt.mixins.helpers import ConfigError, HelpersMixin


class FakeHelpers(HelpersMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True


class TestLoadConfigFromFile:
    def test_loads_valid_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mqtt:
  host: 10.10.10.1
  port: 1883
  username: mqtt_user
  password: mqtt_pass

amcrest:
  hosts:
    - 192.168.1.100
  names:
    - Front Yard
  username: admin
  password: secret
""")
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)

        assert config["mqtt"]["host"] == "10.10.10.1"
        assert config["amcrest"]["username"] == "admin"
        assert config["amcrest"]["hosts"] == ["192.168.1.100"]
        assert config["amcrest"]["names"] == ["Front Yard"]
        assert config["config_from"] == "file"


class TestLoadConfigDefaults:
    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        """When no config file exists, env vars and defaults are used."""
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")

        # amcrest.username and amcrest.password are required
        monkeypatch.setenv("AMCREST_USERNAME", "admin")
        monkeypatch.setenv("AMCREST_PASSWORD", "secret")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)

        assert config["mqtt"]["host"] == "localhost"
        assert config["mqtt"]["port"] == 1883
        assert config["mqtt"]["qos"] == 0
        assert config["mqtt"]["prefix"] == "amcrest2mqtt"
        assert config["mqtt"]["discovery_prefix"] == "homeassistant"
        assert config["config_from"] == "env"


class TestLoadConfigValidation:
    def test_missing_username_password_raises(self, tmp_path):
        """Missing amcrest.username and amcrest.password should raise ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mqtt:
  host: localhost
amcrest:
  hosts:
    - 192.168.1.100
  names:
    - Front Yard
""")
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(ConfigError, match="username.*password"):
                helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)

    def test_mismatched_hosts_names_raises(self, tmp_path):
        """Mismatched hosts/names length should raise ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mqtt:
  host: localhost
amcrest:
  hosts:
    - 192.168.1.100
    - 192.168.1.101
  names:
    - Front Yard
  username: admin
  password: secret
""")
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(ConfigError, match="same length"):
                helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)


class TestLoadConfigVersion:
    def test_app_version_env_overrides_file(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")
        monkeypatch.setenv("APP_VERSION", "v9.9.9")
        monkeypatch.setenv("AMCREST_USERNAME", "admin")
        monkeypatch.setenv("AMCREST_PASSWORD", "secret")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)

        assert config["version"] == "v9.9.9"

    def test_dev_tier_appends_suffix(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.0")
        monkeypatch.setenv("APP_TIER", "dev")
        monkeypatch.setenv("AMCREST_USERNAME", "admin")
        monkeypatch.setenv("AMCREST_PASSWORD", "secret")

        helpers = FakeHelpers()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = helpers.load_config(str(tmp_path))
        finally:
            os.chdir(old_cwd)

        assert config["version"] == "v0.1.0:DEV"


class TestUtilities:
    def test_is_ipv4_valid(self):
        helpers = FakeHelpers()
        assert helpers.is_ipv4("192.168.1.1") is True

    def test_is_ipv4_invalid(self):
        helpers = FakeHelpers()
        assert helpers.is_ipv4("not_an_ip") is False

    def test_mb_to_b(self):
        helpers = FakeHelpers()
        assert helpers.mb_to_b(1) == 1048576

    def test_b_to_mb(self):
        helpers = FakeHelpers()
        assert helpers.b_to_mb(1048576) == 1.0

    def test_b_to_gb(self):
        helpers = FakeHelpers()
        assert helpers.b_to_gb(1073741824) == 1.0


class TestReadFile:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("  hello world  \n")

        helpers = FakeHelpers()
        # read_file replaces newlines; leading/trailing spaces remain unless stripped by replace
        assert helpers.read_file(str(f)) == "  hello world  "

    def test_missing_file_raises(self):
        helpers = FakeHelpers()
        with pytest.raises(FileNotFoundError):
            helpers.read_file("/nonexistent/file.txt")


class TestHandleSignal:
    def test_sets_running_false(self):
        helpers = FakeHelpers()
        assert helpers.running is True

        helpers.handle_signal(2, None)  # SIGINT = 2

        assert helpers.running is False
        helpers.logger.warning.assert_called_once()


class TestUpsertDevice:
    def test_upsert_creates_new_entry(self):
        helpers = FakeHelpers()
        helpers.devices = {}
        helpers.states = {}

        changed = helpers.upsert_device("SERIAL123", component={"device": {"name": "Front Yard"}})

        assert changed is True
        assert "SERIAL123" in helpers.devices
        assert helpers.devices["SERIAL123"]["component"]["device"]["name"] == "Front Yard"

    def test_upsert_same_data_returns_false(self):
        helpers = FakeHelpers()
        helpers.devices = {}
        helpers.states = {}

        helpers.upsert_device("SERIAL123", component={"device": {"name": "Front Yard"}})
        changed = helpers.upsert_device("SERIAL123", component={"device": {"name": "Front Yard"}})

        assert changed is False

    def test_upsert_state_merges_nested_dicts(self):
        helpers = FakeHelpers()
        helpers.devices = {}
        helpers.states = {}

        helpers.upsert_state("SERIAL123", switch={"privacy": "OFF"})
        helpers.upsert_state("SERIAL123", switch={"motion_detection": "ON"})

        assert helpers.states["SERIAL123"]["switch"]["privacy"] == "OFF"
        assert helpers.states["SERIAL123"]["switch"]["motion_detection"] == "ON"
