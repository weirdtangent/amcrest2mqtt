from amcrest import AmcrestCamera, AmcrestError
import asyncio
from asyncio import timeout
from datetime import date
import httpx
import logging
import time
from util import *
from zoneinfo import ZoneInfo

class AmcrestAPI(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # we don't want to get the .info HTTP Request logs from Amcrest
        logging.getLogger("httpx").setLevel(logging.WARNING)

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
        await asyncio.gather(*tasks)

        self.logger.info('Connecting to hosts done.')

        return {d: self.devices[d]['config'] for d in self.devices.keys()}

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
            "storage": {},
        }

    def get_device_storage_stats(self, device_id):
        if 'error' in self.devices[device_id]:
            try:
                self.devices[device_id]['camera'] = self.get_camera(self.devices[device_id]['config']['host'])
                del self.devices[device_id]['error']
            except Exception as err:
                err_msg = f'Problem re-connecting to camera: {err}'
                self.logger.error(err_msg)
                self.devices[device_id]["error"] = err_msg
                raise Exception(err_msg)

        try:
            storage = self.devices[device_id]["camera"].storage_all
        except Exception as err:
            err_msg = f'Problem connecting with camera to get storage stats: {err}'
            self.logger.error(err_msg)
            self.devices[device_id]["error"] = err_msg
            raise Exception(err_msg)
        return { 
            'last_update': str(datetime.now(ZoneInfo(self.timezone))),
            'used_percent': str(storage['used_percent']),
            'used': to_gb(storage['used']),
            'total': to_gb(storage['total']),
        }

    async def collect_all_device_events(self):
        try:
            tasks = [self.get_events_from_device(device_id) for device_id in self.devices]
            await asyncio.gather(*tasks)
            self.logger.info(f'Checked all devices for events')
        except Exception as err:
            self.logger.error(f'collect_all_device_events: {err}')

    async def get_events_from_device(self, device_id):
        try:
            async for code, payload in self.devices[device_id]["camera"].async_event_actions("All"):
                await self.process_device_event(device_id, code, payload)
        except Exception as err:
            self.logger.error(f'get_events_from_device: {err}')
        self.logger.info(f'Checked {device_id} for events')

    async def process_device_event(self, device_id, code, payload):
        try:
            config = self.devices[device_id]['config']

            self.logger.debug(f'Event on {config["host"]} - {code}: {payload}')

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

            self.events.append({ 'device_id': device_id, 'event': code , 'payload': payload['action'] })
            self.logger.info(f'Event(s) appended to queue, queue length now: {len(self.events)}')
        except Exception as err:
            self.logger.error(f'process_device_event: {err}')


    def get_next_event(self):
        if len(self.events) > 0:
            self.logger.info('Found event on queue')
            return self.events.pop(0)

        return None