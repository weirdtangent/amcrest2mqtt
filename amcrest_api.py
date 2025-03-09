from amcrest import AmcrestCamera, AmcrestError
import asyncio
from asyncio import timeout
import base64
from datetime import datetime
import httpx
import logging
import time
from util import *
from zoneinfo import ZoneInfo

class AmcrestAPI(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # we don't want to get this mess of deeper-level logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
        logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
        logging.getLogger("amcrest.http").setLevel(logging.ERROR)
        logging.getLogger("amcrest.event").setLevel(logging.WARNING)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

        self.last_call_date = ''
        self.timezone = config['timezone']

        self.amcrest_config = config['amcrest']

        self.count = len(self.amcrest_config['hosts'])
        self.devices = {}
        self.events = []

    async def connect_to_devices(self):
        self.logger.info(f'Connecting to: {self.amcrest_config["hosts"]}')
        tasks = []

        device_names = self.amcrest_config['names']
        for host in self.amcrest_config['hosts']:
            task = asyncio.create_task(self.get_device(host, device_names.pop(0)))
            tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)

        # return just the config of each device, not the camera object
        return {d: self.devices[d]['config'] for d in self.devices.keys()}

    def reset_connection(self, device_id):
        device = self.devices[device_id]
        device['camera'] = self.get_camera(device['config']['host'])

    def get_camera(self, host):
        return AmcrestCamera(
            host,
            self.amcrest_config['port'],
            self.amcrest_config['username'],
            self.amcrest_config['password'],
            verbose=False,
        ).camera

    async def get_device(self, host, device_name):
        camera = self.get_camera(host)

        try:
            device_type = camera.device_type.replace("type=", "").strip()
            is_ad110 = device_type == "AD110"
            is_ad410 = device_type == "AD410"
            is_doorbell = is_ad110 or is_ad410
            serial_number = camera.serial_number

            if not isinstance(serial_number, str):
                raise Exception(f'Error fetching serial number for {host}: {error}')

            sw_version = camera.software_information[0].replace("version=", "").strip()
            build_version = camera.software_information[1].strip()
            sw_version = f"{sw_version} ({build_version})"

            network_config = dict(item.split('=') for item in camera.network_config.splitlines())
            interface = network_config['table.Network.DefaultInterface']
            ip_address = network_config[f'table.Network.{interface}.IPAddress']
            mac_address = network_config[f'table.Network.{interface}.PhysicalAddress'].upper()

        except AmcrestError as error:
            raise Exception(f'Error fetching camera details for {host}: {error}')

        self.devices[serial_number] = {
            "camera": camera,
            "config": {
                "host": host,
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
                }
            },
        }

    # Storage stats -------------------------------------------------------------------------------

    def get_device_storage_stats(self, device_id):
        try:
            storage = self.devices[device_id]["camera"].storage_all
        except Exception as err:
            self.logger.error(f'Problem connecting with camera to get storage stats: {err}')
            return {}

        return {
            'last_update': str(datetime.now(ZoneInfo(self.timezone))),
            'used_percent': str(storage['used_percent']),
            'used': to_gb(storage['used']),
            'total': to_gb(storage['total']),
        }

    # Snapshots -----------------------------------------------------------------------------------

    async def collect_all_device_snapshots(self):
        tasks = [self.get_snapshot_from_device(device_id) for device_id in self.devices]
        await asyncio.gather(*tasks)

    async def get_snapshot_from_device(self, device_id):
        try:
            image = await self.devices[device_id]["camera"].async_snapshot()
            self.devices[device_id]['snapshot'] = base64.b64encode(image)
            self.logger.debug(f'Processed snapshot from ({device_id}) {len(image)} bytes raw, and {len(self.devices[device_id]['snapshot'])} bytes base64')
        except Exception as err:
            self.logger.error(f'Failed to get snapshot from device ({device_id})')
            pass

    def get_snapshot(self, device_id):
        return self.devices[device_id]['snapshot'] if 'snapshot' in self.devices[device_id] else None

    # Events --------------------------------------------------------------------------------------

    async def collect_all_device_events(self):
        try:
            tasks = [self.get_events_from_device(device_id) for device_id in self.devices]
            await asyncio.gather(*tasks)
        except Exception as err:
            self.logger.error(err, exc_info=True)

    async def get_events_from_device(self, device_id):
        try:
            async for code, payload in self.devices[device_id]["camera"].async_event_actions("All"):
                await self.process_device_event(device_id, code, payload)
        except Exception as err:
            self.logger.error(f'Failed to get events from device ({device_id}), sleeping 60 sec: {err}')
            await asyncio.sleep(60)
            self.reset_connection(device_id)

    async def process_device_event(self, device_id, code, payload):
        try:
            config = self.devices[device_id]['config']

            self.logger.debug(f'Event on {config["host"]} - {code}: {payload}')

            # VideoMotion: motion detection event
            # VideoLoss: video loss detection event
            # VideoBlind: video blind detection event
            # AlarmLocal: alarm detection event
            # StorageNotExist: storage not exist event
            # StorageFailure: storage failure event
            # StorageLowSpace: storage low space event
            # AlarmOutput: alarm output event
            # SmartMotionHuman: human detection event
            # SmartMotionVehicle: vehicle detection event

            if ((code == "ProfileAlarmTransmit" and config["is_ad110"])
            or (code == "VideoMotion" and not config["is_ad110"])):
                motion_payload = "on" if payload["action"] == "Start" else "off"
                self.events.append({ 'device_id': device_id, 'event': 'motion', 'payload': motion_payload })
            elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                human_payload = "on" if payload["action"] == "Start" else "off"
                self.events.append({ 'device_id': device_id, 'event': 'human', 'payload': human_payload })
            elif code == "_DoTalkAction_":
                doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                self.events.append({ 'device_id': device_id, 'event': 'doorbell', 'payload': doorbell_payload })
            elif code == "NewFile":
                # we don't care about recording events for snapshots being recorded every 1+ seconds!
                if not payload["data"]["File"].endswith('.jpg'):
                    file_payload = { 'file': payload["data"]["File"], 'size': payload["data"]["Size"] }
                    self.events.append({ 'device_id': device_id, 'event': 'recording', 'payload': file_payload })
            else:
                self.events.append({ 'device_id': device_id, 'event': code , 'payload': payload['action'] })
        except Exception as err:
            self.logger.error(err, exc_info=True)

    def get_next_event(self):
        return self.events.pop(0) if len(self.events) > 0 else None