# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from amcrest import AmcrestCamera, ApiWrapper
from amcrest.exceptions import LoginError, AmcrestError, CommError
import asyncio
import base64
from collections.abc import Sequence
from datetime import datetime, timedelta
import random
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt


class AmcrestAPIMixin:
    def increase_api_calls(self: Amcrest2Mqtt) -> None:
        if not self.last_call_date or self.last_call_date.date() != datetime.now().date():
            self.api_calls = 0
        self.last_call_date = datetime.now()
        self.api_calls += 1

    async def connect_to_devices(self: Amcrest2Mqtt) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(5)

        async def _connect_device(host: str, name: str, index: int) -> None:
            async with semaphore:
                await self.get_device(host, name, index)

        self.logger.debug(f'connecting to: {self.amcrest_config["hosts"]}')

        tasks = []
        index = 0
        for host, name in zip(self.amcrest_config["hosts"], self.amcrest_config["names"]):
            tasks.append(_connect_device(host, name, index))
            index += 1
        await asyncio.gather(*tasks)

        self.logger.info("connecting to Amcrest hosts done")
        return {d: self.amcrest_devices[d]["config"] for d in self.amcrest_devices.keys()}

    async def get_camera(self: Amcrest2Mqtt, host: str) -> ApiWrapper:
        config = self.amcrest_config
        return AmcrestCamera(
            host,
            config["port"],
            config["username"],
            config["password"],
            verbose=False,
            retries_connection=0,
            timeout_protocol=(4.0, 4.0),  # (connect, read) in seconds
        ).camera

    async def get_device(self: Amcrest2Mqtt, host: str, device_name: str, index: int) -> None:
        def clean_value(value: str | Sequence[str], prefix: str = "") -> str:
            if not isinstance(value, str):
                value = value[0] if isinstance(value, Sequence) else ""

            if prefix and value.startswith(prefix):
                value = value[len(prefix) :]
            return value.strip()

        camera = None

        try:
            host_ip = await self.get_ip_address(host)
            camera = await self.get_camera(host_ip)
            self.increase_api_calls()
        except LoginError:
            self.logger.error(f'invalid username/password to connect to device "{host}", fix in config.yaml')
            return
        except AmcrestError as err:
            self.logger.error(f'unexpected error connecting to device "{host}", check config.yaml: {err!r}')
            return
        except Exception as err:
            self.logger.error(f"error connecting to {host}: {err!r}")
            return

        (
            serial_number,
            device_type,
            sw_info,
            net_config,
            device_class,
            hardware_version,
            vendor_info,
        ) = await asyncio.gather(
            camera.async_serial_number,
            camera.async_device_type,
            camera.async_software_information,
            camera.async_network_config,
            camera.async_device_class,
            camera.async_hardware_version,
            camera.async_vendor_information,
        )

        serial_number = clean_value(serial_number, "SerialNumber=")
        device_class = clean_value(device_class, "deviceClass=")
        device_type = clean_value(device_type, "type=")

        is_ad110 = device_type == "AD110"
        is_ad410 = device_type == "AD410"
        is_doorbell = is_ad110 or is_ad410

        version = sw_info[0].replace("version=", "").strip()
        build = sw_info[1].strip()
        sw_version = f"{version} ({build})"

        if isinstance(net_config, tuple):
            net_config_str = cast(str, net_config[0])
        else:
            net_config_str = cast(str, net_config)
        network_config = dict(item.split("=", 1) for item in net_config_str.splitlines() if "=" in item)

        interface = network_config.get("table.Network.DefaultInterface")
        if not interface:
            # Find first interface key dynamically
            candidates = [k.split(".")[2] for k in network_config if k.startswith("table.Network.") and ".IPAddress" in k]
            interface = candidates[0] if candidates else "eth0"
            self.logger.debug(f"no DefaultInterface key; using {interface}")

        ip_address = network_config.get(f"table.Network.{interface}.IPAddress", "0.0.0.0")
        mac_address = network_config.get(f"table.Network.{interface}.PhysicalAddress", "00:00:00:00:00:00").upper()

        if serial_number not in self.amcrest_devices:
            self.logger.info(f"connected to {host} with serial number {serial_number}")

        self.amcrest_devices[serial_number] = {
            "camera": camera,
            "config": {
                "host": host,
                "index": index,
                "host_ip": host_ip,
                "device_name": device_name,
                "device_type": device_type,
                "device_class": device_class,
                "is_ad110": is_ad110,
                "is_ad410": is_ad410,
                "is_doorbell": is_doorbell,
                "serial_number": serial_number,
                "software_version": sw_version,
                "hardware_version": hardware_version,
                "vendor": vendor_info,
                "network": {
                    "interface": interface,
                    "ip_address": ip_address,
                    "mac": mac_address,
                },
            },
        }

    def reboot_device(self: Amcrest2Mqtt, device_id: str) -> None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None
        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None

        response = device["camera"].reboot().strip()
        self.logger.debug(f"sent reboot signal to {self.get_device_name(device_id)}, {response}")
        if response == "OK":
            self.upsert_state(device_id, internal={"reboot": datetime.now()})
            self.logger.info(f"rebooted {self.get_device_name(device_id)}")
            return
        self.logger.error(f"failed to reboot {self.get_device_name(device_id)}: {response}")

    def is_rebooting(self: Amcrest2Mqtt, device_id: str) -> bool:
        states = self.states[device_id]
        if "reboot" not in states["internal"]:
            return False

        reboot_time = states["internal"]["reboot"]
        if reboot_time + timedelta(minutes=2) > datetime.now():
            return True

        states["internal"].pop("reboot")
        if states["sensor"].get("event_text", "").startswith("Reboot"):
            self.upsert_state(device_id, sensor={"event_text": ""})

        return False

    # Storage stats -------------------------------------------------------------------------------

    async def get_storage_stats(self: Amcrest2Mqtt, device_id: str) -> dict[str, str | float]:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return {}

        device = self.amcrest_devices[device_id]
        states = self.states[device_id]

        # return our last known state if something fails
        current: dict[str, str | float] = (
            {
                "used_percent": states["sensor"].get("storage_used_pct", 0),
                "used": states["sensor"].get("storage_used", 0),
                "total": states["sensor"].get("storage_total", 0),
            }
            if "sensor" in states
            else {}
        )

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            storage = cast(dict, await device["camera"].async_storage_all)
        except CommError as err:
            self.logger.error(f"failed to get storage stats from ({self.get_device_name(device_id)}): {err!r}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to ({self.get_device_name(device_id)}): {err!r}")
            return current

        self.increase_api_calls()

        return {
            "used_percent": storage.get("used_percent", "unknown"),
            "used": self.b_to_gb(storage["used"][0]),
            "total": self.b_to_gb(storage["total"][0]),
        }

    # Privacy config ------------------------------------------------------------------------------

    async def get_privacy_mode(self: Amcrest2Mqtt, device_id: str) -> bool:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return False

        device = self.amcrest_devices[device_id]
        states = self.states[device_id]
        # return our last known state if something fails
        current = True if "sensor" in states and states["sensor"].get("privacy", "OFF") == "ON" else False

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            response = await device["camera"].async_privacy_config()
        except CommError as err:
            self.logger.error(f"failed to get privacy mode from ({self.get_device_name(device_id)}): {err!r}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err!r}")
            return current

        self.increase_api_calls()

        privacy = response if isinstance(response, dict) else {}
        if isinstance(response, str):
            for line in response.strip().split("\n"):
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    privacy[key] = value

        # Extract Enable value from the parsed dictionary
        enable_value = None
        for key in privacy:
            if key.endswith(".Enable") or key == "Enable":
                enable_value = privacy[key]
                break

        if enable_value is None:
            self.logger.warning(f"failed to get privacy mode from ({self.get_device_name(device_id)}), got: {type(privacy)} with value: {privacy}")
            return current

        privacy_mode = bool(enable_value.lower() == "true")
        return privacy_mode

    async def set_privacy_mode(self: Amcrest2Mqtt, device_id: str, switch: bool) -> None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None

        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None
        camera = device["camera"]

        try:
            response = str(await camera.async_set_privacy(switch)).strip()
        except CommError as err:
            self.logger.error(f"failed to set privacy mode on ({self.get_device_name(device_id)}): {err!r}")
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err!r}")

        self.increase_api_calls()
        self.logger.debug(f"set privacy_mode on {self.get_device_name(device_id)} to {switch}, got back: {response}")
        if response == "OK":
            self.upsert_state(device_id, switch={"privacy": "ON" if switch else "OFF"})
            await self.publish_device_state(device_id)
            return None
        self.logger.error(f"failed to set privacy mode on ({self.get_device_name(device_id)}): {response}")
        return None

    # Motion detection config ---------------------------------------------------------------------

    async def get_motion_detection(self: Amcrest2Mqtt, device_id: str) -> bool:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return False

        device = self.amcrest_devices[device_id]
        states = self.states[device_id]

        # return our last known state if something fails
        current = True if "sensor" in states and states["sensor"].get("motion_detection", "OFF") == "ON" else False

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            motion_detection = bool(await device["camera"].async_is_motion_detector_on())
        except CommError as err:
            self.logger.error(f"failed to get motion detection switch on ({self.get_device_name(device_id)}): {err!r}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err!r}")
            return current

        self.increase_api_calls()
        return motion_detection

    async def set_motion_detection(self: Amcrest2Mqtt, device_id: str, switch: bool) -> None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None

        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None
        camera = device["camera"]

        try:
            response = bool(await camera.async_set_motion_detection(switch))
        except CommError:
            self.logger.error(f"failed to communicate with device ({self.get_device_name(device_id)}) to set motion detections")
        except LoginError:
            self.logger.error(f"failed to authenticate with device ({self.get_device_name(device_id)}) to set motion detections")

        self.increase_api_calls()
        self.logger.debug(f"set motion_detection on {self.get_device_name(device_id)} to {switch}, got back: {response}")
        if response:
            self.upsert_state(device_id, switch={"motion_detection": "ON" if switch else "OFF"})
            await self.publish_device_state(device_id)
        return None

    # Snapshots -----------------------------------------------------------------------------------

    async def get_snapshot_from_device(self: Amcrest2Mqtt, device_id: str) -> str | None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None

        device = self.amcrest_devices[device_id]
        timeout = 10
        max_tries = 3
        base_backoff = 5

        # Respect privacy mode (default False if missing)
        if device.get("privacy_mode", False):
            self.logger.info(f"skipping snapshot for {self.get_device_name(device_id)} (privacy mode ON)")
            return None

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None

        camera = device["camera"]

        for attempt in range(1, max_tries + 1):
            try:
                if self.is_rebooting(device_id):
                    return None

                self.logger.debug(f"getting snapshot from {self.get_device_name(device_id)}")
                image_bytes = await asyncio.wait_for(camera.async_snapshot(), timeout=timeout)
                self.increase_api_calls()
                if not image_bytes:
                    self.logger.warning(f"snapshot: empty image from {self.get_device_name(device_id)}, ignoring")
                    return None

                encoded_b = base64.b64encode(image_bytes)
                encoded = encoded_b.decode("ascii")
                self.upsert_state(
                    device_id,
                    camera={"snapshot": encoded},
                    image={"snapshot": encoded},
                )
                await self.publish_device_state(device_id)

                self.logger.debug(f"got snapshot from {self.get_device_name(device_id)} {len(image_bytes)} raw bytes -> {len(encoded)} b64 chars")
                return encoded

            except (CommError, LoginError, asyncio.TimeoutError, Exception) as err:
                self.logger.debug(f"snapshot attempt {attempt}/{max_tries} failed for {self.get_device_name(device_id)}: {err!r}")

            except asyncio.CancelledError:
                self.logger.debug(f"snapshot cancelled for {self.get_device_name(device_id)}, letting shutdown propagate")
                raise

            delay = base_backoff * (2 ** (attempt - 1))
            delay += random.uniform(0, 5)
            await asyncio.sleep(delay)

        self.logger.info(f"getting snapshot failed after {max_tries} tries for {self.get_device_name(device_id)}")
        return None

    # Recorded file -------------------------------------------------------------------------------

    async def get_recorded_file(self: Amcrest2Mqtt, device_id: str, file: str, encode: bool = True) -> str | None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None

        device = self.amcrest_devices[device_id]
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                if self.is_rebooting(device_id):
                    return None

                data_raw = cast(bytes, device["camera"].download_file(file))
                self.increase_api_calls()
                if data_raw:
                    if not encode:
                        if len(data_raw) < self.mb_to_b(100):
                            return data_raw.decode("latin-1")
                        else:
                            self.logger.warning(f"skipping raw recording, too large: {self.b_to_mb(len(data_raw))} MB")
                            return None
                    data_base64 = base64.b64encode(data_raw)
                    self.logger.debug(
                        f"processed recording from ({self.get_device_name(device_id)}) {len(data_raw)} bytes raw, and {len(data_base64)} bytes base64"
                    )
                    if len(data_base64) < self.mb_to_b(100):
                        return data_raw.decode("latin-1")
                    else:
                        self.logger.error(f"skipping recording, too large: {self.b_to_mb(len(data_base64))} MB")
                        return None
            except CommError as err:
                self.logger.debug(f"failed to get recording from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")
            except LoginError as err:
                self.logger.debug(f"failed to get recording from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")
            except Exception as err:  # noqa: BLE001 (log-and-drop is intentional here)
                self.logger.debug(f"failed to get recording from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")

        self.logger.error(f"failed to get recording from ({self.get_device_name(device_id)}) after {max_attempts} attempts")
        return None

    # Events --------------------------------------------------------------------------------------

    async def get_events_from_device(self: Amcrest2Mqtt, device_id: str) -> None:
        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None
        camera = device["camera"]

        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                if self.is_rebooting(device_id):
                    return None

                async for code, payload in camera.async_event_actions("All"):
                    await self.process_device_event(device_id, code, payload)
                self.increase_api_calls()
                return
            except CommError as err:
                self.logger.debug(f"failed to get events from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")
            except LoginError as err:
                self.logger.debug(f"failed to get events from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")
            except Exception as err:  # noqa: BLE001 (log-and-drop is intentional here)
                self.logger.debug(f"failed to get events from ({self.get_device_name(device_id)}) on attempt {attempt}: {err!r}")

        self.logger.error(f"failed to check for events on ({self.get_device_name(device_id)}) after {max_attempts} attempts ")

    async def process_device_event(self: Amcrest2Mqtt, device_id: str, code: str, payload: Any) -> None:
        if device_id not in self.amcrest_devices:
            self.logger.warning(f"device not found for {self.get_device_name(device_id)}")
            return None

        device = self.amcrest_devices[device_id]
        config = device["config"]

        try:
            if (code == "ProfileAlarmTransmit" and config["is_ad110"]) or (code == "VideoMotion" and not config["is_ad110"]):
                motion_payload = {"state": "on" if payload["action"] == "Start" else "off", "region": ", ".join(payload["data"]["RegionName"])}
                self.events.append({"device_id": device_id, "event": "motion", "payload": motion_payload})
            elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                human_payload = "on" if payload["action"] == "Start" else "off"
                self.events.append({"device_id": device_id, "event": "human", "payload": human_payload})
            elif code == "_DoTalkAction_":
                doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                self.events.append({"device_id": device_id, "event": "doorbell", "payload": doorbell_payload})
            elif code == "NewFile":
                if (
                    "File" in payload["data"]
                    and "[R]" not in payload["data"]["File"]
                    and ("StoragePoint" not in payload["data"] or payload["data"]["StoragePoint"] != "Temporary")
                ):
                    file_payload = {"file": payload["data"]["File"], "size": payload["data"]["Size"]}
                    self.events.append({"device_id": device_id, "event": "recording", "payload": file_payload})
            elif code == "LensMaskOpen":
                device["privacy_mode"] = True
                self.events.append({"device_id": device_id, "event": "privacy_mode", "payload": "on"})
            elif code == "LensMaskClose":
                device["privacy_mode"] = False
                self.events.append({"device_id": device_id, "event": "privacy_mode", "payload": "off"})

            # lets send these but not bother logging them here
            elif code in ["TimeChange", "NTPAdjustTime", "RtspSessionDisconnect"]:
                self.events.append({"device_id": device_id, "event": code, "payload": payload["action"]})

            # lets just ignore these completely
            elif code in ["InterVideoAccess", "VideoMotionInfo"]:
                pass

            # save everything else as a 'generic' event
            else:
                self.logger.info(f"logged event on {self.get_device_name(device_id)} - {code}: {payload}")
                self.events.append({"device_id": device_id, "event": code, "payload": payload})
        except Exception as err:
            self.logger.error(f"failed to process event from {self.get_device_name(device_id)}: {err!r}")

    def get_next_event(self: Amcrest2Mqtt) -> dict[str, Any] | None:
        return self.events.pop(0) if len(self.events) > 0 else None
