from amcrest import AmcrestCamera, AmcrestError
import asyncio
from datetime import date
import time
from util import *
from zoneinfo import ZoneInfo

class AmcrestAPI(object):
    def __init__(self, config):
        self.last_call_date = ''
        self.timezone = config['timezone']
        self.hide_ts = config['hide_ts'] or False

        self.amcrest_config = config['amcrest']

        self.count = len(self.amcrest_config['hosts'])
        self.devices = {}

    def log(self, msg, level='INFO'):
        app_log(msg, level=level, tz=self.timezone, hide_ts=self.hide_ts)

    async def connect_to_devices(self):
        self.log(f'Connecting to: {self.amcrest_config["hosts"]}')
        tasks = []

        device_names = self.amcrest_config['names']
        for host in self.amcrest_config['hosts']:
            task = asyncio.create_task(self.get_device(host, device_names.pop(0)))
            tasks.append(task)
        await asyncio.gather(*tasks)

        self.log(f"Connecting to hosts done.", level="INFO")

        return {d: self.devices[d]['config'] for d in self.devices.keys()}

    def get_camera(self, host):
        return AmcrestCamera(
            host, self.amcrest_config['port'], self.amcrest_config['username'], self.amcrest_config['password']
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
            amcrest_version = f"{sw_version} ({build_version})"

            vendor = camera.vendor_information
            hardware_version = camera.hardware_version
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
                "software_version": amcrest_version,
                "hardware_version": hardware_version,
                "vendor": vendor,
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
                self.log(err_msg, level='ERROR')
                self.devices[device_id]["error"] = err_msg
                raise Exception(err_msg)

        try:
            storage = self.devices[device_id]["camera"].storage_all
        except Exception as err:
            err_msg = f'Problem connecting with camera to get storage stats: {err}'
            self.log(err_msg, level='ERROR')
            self.devices[device_id]["error"] = err_msg
            raise Exception(err_msg)
        return { 
            'last_update': str(datetime.now(ZoneInfo(self.timezone))),
            'used_percent': str(storage['used_percent']),
            'used': to_gb(storage['used']),
            'total': to_gb(storage['total']),
        }

    async def get_device_event_actions(self, device_id):
        events = []
        device = self.devices[device_id]
        config = device['config']
        async for code, payload in device["camera"].async_event_actions("All"):
            self.log(f"Event on {config['host']} - {code}: {payload['action']}")
            if ((code == "ProfileAlarmTransmit" and config["is_ad110"])
            or (code == "VideoMotion" and not config["is_ad110"])):
                motion_payload = "on" if payload["action"] == "Start" else "off"
                events.append({ 'event': 'motion', 'payload': motion_payload })
            elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                human_payload = "on" if payload["action"] == "Start" else "off"
                events.append({ 'event': 'human', 'payload': human_payload })
            elif code == "_DoTalkAction_":
                doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                events.append({ 'event': 'doorbell', 'payload': doorbell_payload })

            events.append({ 'event': 'event', 'payload': payload })
        return events