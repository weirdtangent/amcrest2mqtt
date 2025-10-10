import logging
import os
import socket
import yaml

def get_ip_address(hostname: str) -> str:
    """
    Resolve a hostname to an IP address (IPv4 or IPv6).

    Returns:
        str: The resolved IP address, or the original hostname if resolution fails.
    """
    if not hostname:
        return hostname

    try:
        # Try both IPv4 and IPv6 (AF_UNSPEC)
        infos = socket.getaddrinfo(
            hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        # Prefer IPv4 addresses if available
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                return sockaddr[0]
        # Otherwise, fallback to first valid IPv6
        return infos[0][4][0] if infos else hostname
    except socket.gaierror as e:
        logging.debug(f"DNS lookup failed for {hostname}: {e}")
    except Exception as e:
        logging.debug(f"Unexpected error resolving {hostname}: {e}")

    return hostname


def to_gb(bytes_value):
    """Convert bytes to a rounded string in gigabytes."""
    try:
        gb = float(bytes_value) / (1024**3)
        return f"{gb:.2f} GB"
    except Exception:
        return "0.00 GB"


def read_file(file_name, strip_newlines=True, default=None, encoding="utf-8"):
    try:
        with open(file_name, "r", encoding=encoding) as f:
            data = f.read()
            return data.replace("\n", "") if strip_newlines else data
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def read_version():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    version_path = os.path.join(base_dir, "VERSION")
    try:
        with open(version_path, "r") as f:
            return f.read().strip() or "unknown"
    except FileNotFoundError:
        env_version = os.getenv("APP_VERSION")
        return env_version.strip() if env_version else "unknown"


def load_config(path=None):
    """Load and normalize configuration from YAML file or directory."""

    logger = logging.getLogger(__name__)
    default_path = "/config/config.yaml"

    # Resolve config path
    config_path = path or default_path
    if os.path.isdir(config_path):
        config_path = os.path.join(config_path, "config.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    # --- Normalization helpers ------------------------------------------------
    def to_bool(value):
        """Coerce common truthy/falsey forms to proper bool."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if value is None:
            return False
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    def normalize_section(section, bool_keys):
        """Normalize booleans within a nested section."""
        if not isinstance(config.get(section), dict):
            return
        for key in bool_keys:
            if key in config[section]:
                config[section][key] = to_bool(config[section][key])

    # --- Global defaults + normalization -------------------------------------
    config.setdefault("version", "1.0.0")
    config.setdefault("debug", False)
    config.setdefault("hide_ts", False)
    config.setdefault("timezone", "UTC")

    # normalize top-level flags
    config["debug"] = to_bool(config.get("debug"))
    config["hide_ts"] = to_bool(config.get("hide_ts"))

    # Example: normalize booleans within sections
    normalize_section("mqtt", ["tls", "retain", "clean_session"])
    normalize_section("amcrest", ["webrtc", "verify_ssl"])
    normalize_section("service", ["enabled", "auto_restart"])

    # Add metadata for debugging/logging
    config["config_path"] = os.path.abspath(config_path)
    config["config_from"] = "file" if os.path.exists(config_path) else "defaults"

    return config
