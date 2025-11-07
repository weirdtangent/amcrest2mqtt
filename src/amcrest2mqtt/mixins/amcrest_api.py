# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from amcrest import AmcrestCamera
from amcrest.exceptions import LoginError, AmcrestError, CommError
import asyncio
import base64
from datetime import datetime
import random
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from amcrest2mqtt.interface import AmcrestServiceProtocol as Amcrest2Mqtt

SNAPSHOT_TIMEOUT_S = 10
SNAPSHOT_MAX_TRIES = 3
SNAPSHOT_BASE_BACKOFF_S = 5


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
                await asyncio.to_thread(self.get_device, host, name, index)

        self.logger.debug(f'connecting to: {self.amcrest_config["hosts"]}')

        tasks = []
        index = 0
        for host, name in zip(self.amcrest_config["hosts"], self.amcrest_config["names"]):
            tasks.append(_connect_device(host, name, index))
            index += 1
        await asyncio.gather(*tasks)

        self.logger.info("connecting to hosts done")
        return {d: self.amcrest_devices[d]["config"] for d in self.amcrest_devices.keys()}

    def get_camera(self: Amcrest2Mqtt, host: str) -> AmcrestCamera:
        config = self.amcrest_config
        self.increase_api_calls()
        return AmcrestCamera(host, config["port"], config["username"], config["password"], verbose=False)

    def get_device(self: Amcrest2Mqtt, host: str, device_name: str, index: int) -> None:
        camera = None

        try:
            host_ip = self.get_ip_address(host)
            device = self.get_camera(host_ip)
            camera = device.camera
            self.increase_api_calls()
        except LoginError:
            self.logger.error(f'invalid username/password to connect to device "{host}", fix in config.yaml')
            return
        except AmcrestError as err:
            self.logger.error(f'unexpected error connecting to device "{host}", check config.yaml: {err}')
            return
        except Exception as err:
            self.logger.error(f"error connecting to {host}: {err}")
            return

        serial_number = camera.serial_number

        device_type = camera.device_type.replace("type=", "").strip()
        is_ad110 = device_type == "AD110"
        is_ad410 = device_type == "AD410"
        is_doorbell = is_ad110 or is_ad410

        version = camera.software_information[0].replace("version=", "").strip()
        build = camera.software_information[1].strip()
        sw_version = f"{version} ({build})"

        network_config = dict(item.split("=") for item in camera.network_config.splitlines())
        interface = network_config["table.Network.DefaultInterface"]
        ip_address = network_config[f"table.Network.{interface}.IPAddress"]
        mac_address = network_config[f"table.Network.{interface}.PhysicalAddress"].upper()

        if camera.serial_number not in self.amcrest_devices:
            self.logger.info(f"connected to {host} with serial number {camera.serial_number}")

        self.amcrest_devices[serial_number] = {
            "camera": camera,
            "config": {
                "host": host,
                "index": index,
                "host_ip": host_ip,
                "device_name": device_name,
                "device_type": device_type,
                "device_class": camera.device_class,
                "is_ad110": is_ad110,
                "is_ad410": is_ad410,
                "is_doorbell": is_doorbell,
                "serial_number": serial_number,
                "software_version": sw_version,
                "hardware_version": camera.hardware_version,
                "vendor": camera.vendor_information,
                "network": {
                    "interface": interface,
                    "ip_address": ip_address,
                    "mac": mac_address,
                },
            },
        }

    # Storage stats -------------------------------------------------------------------------------

    def get_storage_stats(self: Amcrest2Mqtt, device_id: str) -> dict[str, str | float]:
        device = self.amcrest_devices[device_id]
        states = self.states[device_id]

        # return our last known state if we fail to get new stats
        current: dict[str, str | float] = {
            "used_percent": states["sensor"]["storage_used_pct"],
            "used": states["sensor"]["storage_used"],
            "total": states["sensor"]["storage_total"],
        }

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            storage = device["camera"].storage_all
            self.increase_api_calls()
        except CommError as err:
            self.logger.error(f"failed to get storage stats from ({self.get_device_name(device_id)}): {err}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to ({self.get_device_name(device_id)}): {err}")
            return current

        return {
            "used_percent": storage.get("used_percent", "unknown"),
            "used": self.b_to_gb(storage["used"][0]),
            "total": self.b_to_gb(storage["total"][0]),
        }

    # Privacy config ------------------------------------------------------------------------------

    def get_privacy_mode(self: Amcrest2Mqtt, device_id: str) -> bool:
        device = self.amcrest_devices[device_id]
        states = self.states[device_id]

        # return our last known state if we fail to get new stats
        current = bool(states["sensor"]["privacy"] == "ON")

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            privacy = device["camera"].privacy_config().split()
            privacy_mode = True if privacy[0].split("=")[1] == "true" else False
            device["privacy_mode"] = privacy_mode
            self.increase_api_calls()
        except CommError as err:
            self.logger.error(f"failed to get privacy mode from ({self.get_device_name(device_id)}): {err}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err}")
            return current

        return privacy_mode

    def set_privacy_mode(self: Amcrest2Mqtt, device_id: str, switch: bool) -> str:
        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return ""

        try:
            response = cast(str, device["camera"].set_privacy(switch).strip())
            self.increase_api_calls()
        except CommError as err:
            self.logger.error(f"failed to set privacy mode on ({self.get_device_name(device_id)}): {err}")
            return ""
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err}")
            return ""

        return response

    # Motion detection config ---------------------------------------------------------------------

    def get_motion_detection(self: Amcrest2Mqtt, device_id: str) -> bool:
        device = self.amcrest_devices[device_id]
        states = self.states[device_id]

        # return our last known state if we fail to get new stats
        current = bool(states["sensor"]["motion_detection"] == "ON")

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return current

        try:
            motion_detection = bool(device["camera"].is_motion_detector_on())
            self.increase_api_calls()
        except CommError as err:
            self.logger.error(f"failed to get motion detection switch on ({self.get_device_name(device_id)}): {err}")
            return current
        except LoginError as err:
            self.logger.error(f"failed to auth to device ({self.get_device_name(device_id)}): {err}")
            return current

        return motion_detection

    def set_motion_detection(self: Amcrest2Mqtt, device_id: str, switch: bool) -> str:
        device = self.amcrest_devices[device_id]

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return ""

        try:
            response = str(device["camera"].set_motion_detection(switch))
            self.increase_api_calls()
        except CommError:
            self.logger.error(f"Failed to communicate with device ({self.get_device_name(device_id)}) to set motion detections")
            return ""
        except LoginError:
            self.logger.error(f"Failed to authenticate with device ({self.get_device_name(device_id)}) to set motion detections")
            return ""

        return response

    # Snapshots -----------------------------------------------------------------------------------

    async def collect_all_device_snapshots(self: Amcrest2Mqtt) -> None:
        tasks = [self.get_snapshot_from_device(device_id) for device_id in self.amcrest_devices]
        await asyncio.gather(*tasks)

    async def get_snapshot_from_device(self: Amcrest2Mqtt, device_id: str) -> str | None:
        device = self.amcrest_devices[device_id]

        # Respect privacy mode (default False if missing)
        if device.get("privacy_mode", False):
            self.logger.info(f"skipping snapshot for {self.get_device_name(device_id)} (privacy mode ON)")
            return None

        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None
        camera = device["camera"]

        for attempt in range(1, SNAPSHOT_MAX_TRIES + 1):
            try:
                image_bytes = await asyncio.wait_for(camera.async_snapshot(), timeout=SNAPSHOT_TIMEOUT_S)
                self.increase_api_calls()
                if not image_bytes:
                    self.logger.warning(f"Snapshot: empty image from {self.get_device_name(device_id)}")
                    return None

                encoded_b = base64.b64encode(image_bytes)
                encoded = encoded_b.decode("ascii")
                self.upsert_state(
                    device_id,
                    image={"snapshot": encoded},
                )
                self.publish_device_state(device_id)

                self.logger.debug(f"got snapshot from {self.get_device_name(device_id)} {len(image_bytes)} raw bytes -> {len(encoded)} b64 chars")
                return encoded

            except asyncio.CancelledError:
                # Let shutdown propagate
                raise

            except (CommError, LoginError, asyncio.TimeoutError) as err:
                # Backoff with jitter before retrying
                if attempt == SNAPSHOT_MAX_TRIES:
                    break
                delay = SNAPSHOT_BASE_BACKOFF_S * (2 ** (attempt - 1))
                delay += random.uniform(0, 0.25)
                self.logger.debug(
                    f"snapshot attempt {attempt}/{SNAPSHOT_MAX_TRIES} failed for {self.get_device_name(device_id)}: {err!r}; retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

            # Any other unexpected exception: log and stop
            except Exception as err:  # noqa: BLE001 (log-and-drop is intentional here)
                self.logger.exception(f"snapshot: unexpected error for {self.get_device_name(device_id)}: {err!r}")
                return None

        self.logger.info(f"getting snapshot failed after {SNAPSHOT_MAX_TRIES} tries for {self.get_device_name(device_id)}")
        return None

    def get_snapshot(self: Amcrest2Mqtt, device_id: str) -> str | None:
        return self.amcrest_devices[device_id]["snapshot"] if "snapshot" in self.devices[device_id] else None

    # Recorded file -------------------------------------------------------------------------------

    def get_recorded_file(self: Amcrest2Mqtt, device_id: str, file: str, encode: bool = True) -> str | None:
        device = self.amcrest_devices[device_id]

        tries = 0
        while tries < 3:
            try:
                data_raw = cast(bytes, device["camera"].download_file(file))
                self.increase_api_calls()
                if data_raw:
                    if not encode:
                        if len(data_raw) < self.mb_to_b(100):
                            return data_raw.decode("latin-1")
                        else:
                            self.logger.error(f"skipping raw recording, too large: {self.b_to_mb(len(data_raw))} MB")
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
            except CommError:
                tries += 1
            except LoginError:
                tries += 1

        self.logger.error(f"failed to get recording from ({self.get_device_name(device_id)})")
        return None

    # Events --------------------------------------------------------------------------------------

    async def collect_all_device_events(self: Amcrest2Mqtt) -> None:
        tasks = [self.get_events_from_device(device_id) for device_id in self.amcrest_devices]
        await asyncio.gather(*tasks)

    async def get_events_from_device(self: Amcrest2Mqtt, device_id: str) -> None:
        device = self.amcrest_devices[device_id]
        if not device["camera"]:
            self.logger.warning(f"camera not found for {self.get_device_name(device_id)}")
            return None

        tries = 0
        while tries < 3:
            try:
                async for code, payload in device["camera"].async_event_actions("All"):
                    await self.process_device_event(device_id, code, payload)
                self.increase_api_calls()
                return
            except CommError:
                tries += 1
            except LoginError:
                tries += 1

        self.logger.error(f"failed to check for events on ({self.get_device_name(device_id)})")

    async def process_device_event(self: Amcrest2Mqtt, device_id: str, code: str, payload: Any) -> None:
        try:
            device = self.amcrest_devices[device_id]
            config = device["config"]

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
            elif code == "TimeChange":
                self.events.append({"device_id": device_id, "event": code, "payload": payload["action"]})
            elif code == "NTPAdjustTime":
                self.events.append({"device_id": device_id, "event": code, "payload": payload["action"]})
            elif code == "RtspSessionDisconnect":
                self.events.append({"device_id": device_id, "event": code, "payload": payload["action"]})

            # lets just ignore these
            elif code == "InterVideoAccess":  # I think this is US, accessing the API of the camera, lets not inception!
                pass
            elif code == "VideoMotionInfo":
                pass

            # save everything else as a 'generic' event
            else:
                self.logger.info(f"logged event on {self.get_device_name(device_id)} - {code}: {payload}")
                self.events.append({"device_id": device_id, "event": code, "payload": payload})
        except Exception as err:
            self.logger.error(f"failed to process event from {self.get_device_name(device_id)}: {err}", exc_info=True)

    def get_next_event(self: Amcrest2Mqtt) -> dict[str, Any] | None:
        return self.events.pop(0) if len(self.events) > 0 else None
