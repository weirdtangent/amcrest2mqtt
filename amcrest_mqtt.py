import asyncio
from datetime import date
import amcrest_api
import json
import logging
import paho.mqtt.client as mqtt
import random
import signal
import ssl
import string
import time
from util import *
from zoneinfo import ZoneInfo

class AmcrestMqtt(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)
        self.running = False

        self.timezone = config['timezone']

        self.mqttc = None
        self.mqtt_connect_time = None

        self.config = config
        self.mqtt_config = config['mqtt']
        self.amcrest_config = config['amcrest']

        self.client_id = self.get_new_client_id()

        self.version = config['version']

        self.device_update_interval = config['amcrest'].get('device_update_interval', 600)

        self.service_name = self.mqtt_config['prefix'] + ' service'
        self.service_slug = self.mqtt_config['prefix'] + '-service'

        self.devices = {}
        self.configs = {}

    async def _handle_sigterm(self, loop, tasks):
        self.running = False
        self.logger.warn('SIGTERM received, waiting for tasks to cancel...')

        for t in tasks:
            t.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    def __enter__(self):
        self.mqttc_create()
        self.amcrestc = amcrest_api.AmcrestAPI(self.config)
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        self.logger.info('Exiting gracefully')

        if self.mqttc is not None and self.mqttc.is_connected():
            for device_id in self.devices:
                self.devices[device_id]['availability'] = 'offline'
                if 'state' not in self.devices[device_id]:
                    self.devices[device_id]['state'] = {}
                self.publish_device(device_id)

            self.mqttc.disconnect()
        else:
            self.logger.info('Lost connection to MQTT')

    # MQTT Functions
    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            self.logger.error(f'MQTT CONNECTION ISSUE ({rc})')
            exit()
        self.logger.info(f'MQTT connected as {self.client_id}')
        client.subscribe(self.get_device_sub_topic())
        client.subscribe(self.get_attribute_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        self.logger.info('MQTT connection closed')

        # if reconnect, lets use a new client_id
        self.client_id = self.get_new_client_id()

        if time.time() > self.mqtt_connect_time + 10:
            self.mqttc_create()
        else:
            exit()

    def mqtt_on_log(self, client, userdata, paho_log_level, msg):
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            self.logger.error(f'MQTT LOG: {msg}')
        elif paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            self.logger.warn(f'MQTT LOG: {msg}')

    def mqtt_on_message(self, client, userdata, msg):
        if not msg or not msg.payload:
            return
        topic = msg.topic
        payload = json.loads(msg.payload)

        self.logger.info(f'Got MQTT message for {topic} - {payload}')

        # we might get:
        # device/component/set
        # device/component/set/attribute
        # homeassistant/device/component/set
        # homeassistant/device/component/set/attribute
        components = topic.split('/')

        # handle this message if it's for us, otherwise pass along to amcrest API
        if components[-2] == self.get_component_slug('service'):
            self.handle_service_message(None, payload)
        elif components[-3] == self.get_component_slug('service'):
            self.handle_service_message(components[-1], payload)
        else:
            if components[-1] == 'set':
                mac = components[-2][-16:]
            elif components[-2] == 'set':
                mac = components[-3][-16:]
            else:
                self.logger.error(f'UNKNOWN MQTT MESSAGE STRUCTURE: {topic}')
                return
            # ok, lets format the device_id and send to amcrest
            device_id = ':'.join([mac[i:i+2] for i in range (0, len(mac), 2)])
            self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)
        self.logger.debug(f'MQTT SUBSCRIBED: reason_codes - {'; '.join(rc_list)}')

    # MQTT Helpers
    def mqttc_create(self):
        self.mqttc = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=False,
        )

        if self.mqtt_config.get('tls_enabled'):
            self.mqttcnt.tls_set(
                ca_certs=self.mqtt_config.get('tls_ca_cert'),
                certfile=self.mqtt_config.get('tls_cert'),
                keyfile=self.mqtt_config.get('tls_key'),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )
        else:
            self.mqttc.username_pw_set(
                username=self.mqtt_config.get('username'),
                password=self.mqtt_config.get('password'),
            )

        self.mqttc.on_connect = self.mqtt_on_connect
        self.mqttc.on_disconnect = self.mqtt_on_disconnect
        self.mqttc.on_message = self.mqtt_on_message
        self.mqttc.on_subscribe = self.mqtt_on_subscribe
        self.mqttc.on_log = self.mqtt_on_log

        # self.mqttc.will_set(self.get_state_topic(self.service_slug) + '/availability', payload="offline", qos=0, retain=True)

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.error(f'COULD NOT CONNECT TO MQTT {self.mqtt_config.get("host")}: {error}')
            exit(1)

    # MQTT Topics
    def get_new_client_id(self):
        return self.mqtt_config['prefix'] + '-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

    def get_slug(self, device_id, type):
        return f"amcrest_{device_id.replace(':','')}_{type}"

    def get_device_sub_topic(self):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/+/set"
        return f"{self.mqtt_config['discovery_prefix']}/device/+/set"

    def get_attribute_sub_topic(self):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/+/set"
        return f"{self.mqtt_config['discovery_prefix']}/device/+/set/+"

    def get_component_slug(self, device_id):
        return f"amcrest-{device_id.replace(':','')}"

    def get_command_topic(self, device_id, attribute_name):
        if attribute_name:
            if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
                return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/set/{attribute_name}"
            return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/set/{attribute_name}"
        else:
            if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
                return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/set"
            return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/set"

    def get_discovery_topic(self, device_id, topic):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/{topic}"
        return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/{topic}"

    # Service Device
    def publish_service_device(self):
        state_topic = self.get_discovery_topic('service', 'state')
        command_topic = self.get_discovery_topic('service', 'set')
        availability_topic = self.get_discovery_topic('service', 'availability')

        self.mqttc.publish(
            self.get_discovery_topic('service','config'),
            json.dumps({
                'qos': 0,
                'state_topic': state_topic,
                'availability_topic': availability_topic,
                'device': {
                    'name': self.service_name,
                    'ids': self.service_slug,
                    'suggested_area': 'House',
                    'manufacturer': 'weirdTangent',
                    'model': self.version,
                },
                'origin': {
                    'name': self.service_name,
                    'sw_version': self.version,
                    'support_url': 'https://github.com/weirdtangent/amcrest2mqtt',
                },
                'components': {
                    self.service_slug + '_status': {
                        'name': 'Service',
                        'platform': 'binary_sensor',
                        'schema': 'json',
                        'payload_on': 'online',
                        'payload_off': 'offline',
                        'icon': 'mdi:language-python',
                        'state_topic': state_topic,
                        'availability_topic': availability_topic,
                        'value_template': '{{ value_json.status }}',
                        'unique_id': 'amcrest_service_status',
                    },
                    self.service_slug + '_device_refresh': {
                        'name': 'Device Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 10,
                        'max': 3600,
                        'state_topic': state_topic,
                        'command_topic': self.get_command_topic('service', 'device_refresh'),
                        'availability_topic': availability_topic,
                        'value_template': '{{ value_json.device_refresh }}',
                        'unique_id': 'amcrest_service_device_refresh',
                    },
                },
            }),
            retain=True
        )
        self.update_service_device()

    def update_service_device(self):
        self.mqttc.publish(self.get_discovery_topic('service','availability'), 'online', retain=True)
        self.mqttc.publish(
            self.get_discovery_topic('service','state'),
            json.dumps({
                'status': 'online',
                'device_refresh': self.device_update_interval,
            }),
            retain=True
        )


    # amcrest Helpers
    async def setup_devices(self):
        self.logger.info(f'Setup devices')

        try:
            devices = await self.amcrestc.connect_to_devices()
        except Exception as err:
            self.logger.error(f'Failed to connect to 1 or more devices {err}')
            exit(1)

        self.publish_service_device()
        for device_id in devices:
            config = devices[device_id]

            if 'device_type' in config:
                first = False
                if device_id not in self.devices:
                    first = True
                    self.devices[device_id] = {}
                    self.configs[device_id] = config
                    self.devices[device_id]['qos'] = 0
                    self.devices[device_id]['state_topic'] = self.get_discovery_topic(device_id, 'state')
                    self.devices[device_id]['availability_topic'] = self.get_discovery_topic(device_id, 'availability')
                    self.devices[device_id]['command_topic'] = self.get_discovery_topic(device_id, 'set')
                    # self.mqttc.will_set(self.get_state_topic(device_id)+'/availability', payload="offline", qos=0, retain=True)

                self.devices[device_id]['device'] = {
                    'name': config['device_name'],
                    'manufacturer': config['vendor'],
                    'model': config['device_type'],
                    'ids': device_id,
                    'sw_version': config['software_version'],
                    'hw_version': config['hardware_version'],
                    'connections': [
                        ['host', config['host']],
                        ['mac', config['network']['mac']],
                        ['ip address', config['network']['ip_address']],
                    ],
                    'configuration_url': 'http://' + config['host'] + '/',
                    'via_device': self.service_slug,
                }
                self.devices[device_id]['origin'] = {
                    'name': self.service_name,
                    'sw_version': self.version,
                    'support_url': 'https://github.com/weirdtangent/amcrest2mqtt',
                }
                self.add_components_to_device(device_id)
                
                if first:
                    self.logger.info(f'Adding device: "{config['device_name']}" [Amcrest {config["device_type"]}] ({device_id})')
                    self.send_device_discovery(device_id)
                else:
                    self.logger.debug(f'Updated device: {self.devices[device_id]['device']['name']}')
                
                # device discovery sent, now it is save to add these to the dict
                self.devices[device_id]['state'] = {}
                self.devices[device_id]['availability'] = 'online'
            else:
                if first_time_through:
                    self.logger.info(f'Saw device, but not supported yet: "{config["device_name"]}" [amcrest {config["device_type"]}] ({device_id})')

    # add amcrest components to devices
    def add_components_to_device(self, device_id):
        device = self.devices[device_id]
        config = self.configs[device_id]
        components = {}

        if config['is_doorbell']:
            doorbell_name = 'Doorbell' if config['device_name'] == 'Doorbell' else f'{config["device_name"]} Doorbell'
            components[self.get_slug(device_id, 'doorbell')] = {
                'name': doorbell_name,
                'platform': 'binary_sensor',
                'payload_on': 'on',
                'payload_off': 'off',
                'device_class': '',
                'icon': 'mdi:doorbell',
                'state_topic': self.get_discovery_topic(device_id, 'doorbell'),
                'value_template': '{{ value_json.doorbell }}',
                'unique_id': self.get_slug(device_id, 'doorbell'),
            }

        if config['is_ad410']:
            components[self.get_slug(device_id, 'human')] = {
                'name': 'Human',
                'platform': 'binary_sensor',
                'payload_on': 'on',
                'payload_off': 'off',
                'device_class': 'motion',
                'state_topic': self.get_discovery_topic(device_id, 'human'),
                'value_template': '{{ value_json.human }}',
                'unique_id': self.get_slug(device_id, 'human'),
            }

        components[self.get_slug(device_id, 'motion')] = {
            'name': 'Motion',
            'platform': 'binary_sensor',
            'payload_on': 'on',
            'payload_off': 'off',
            'device_class': 'motion',
            'state_topic': self.get_discovery_topic(device_id, 'motion'),
            'unique_id': self.get_slug(device_id, 'motion'),
        }

        components[self.get_slug(device_id, 'version')] = {
            'name': 'Version',
            'platform': 'sensor',
            'icon': 'mdi:package-up',
            'state_topic': device['state_topic'],
            'value_template': '{{ value_json.sw_version }}',
            'entity_category': 'diagnostic',
            'unique_id': self.get_slug(device_id, 'sw_version'),
        }

        components[self.get_slug(device_id, 'serial_number')] = {
            'name': 'Serial Number',
            'platform': 'sensor',
            'icon': 'mdi:identifier',
            'state_topic': device['state_topic'],
            'value_template': '{{ value_json.serial_number }}',
            'entity_category': 'diagnostic',
            'unique_id': self.get_slug(device_id, 'serial_number'),
        }

        components[self.get_slug(device_id, 'host')] = {
            'name': 'Host',
            'platform': 'sensor',
            'icon': 'mdi:ip-network',
            'state_topic': device['state_topic'],
            'value_template': '{{ value_json.host }}',
            'entity_category': 'diagnostic',
            'unique_id': self.get_slug(device_id, 'host'),
        }

        components[self.get_slug(device_id, 'event')] = {
            'name': 'Event',
            'platform': 'sensor',
            'state_topic': self.get_discovery_topic(device_id, 'event'),
            'unique_id': self.get_slug(device_id, 'event'),
        }

        components[self.get_slug(device_id, 'storage_used_percent')] = {
            'name': 'Storage Used %',
            'platform': 'sensor',
            'icon': 'mdi:micro-sd',
            'unit_of_measurement': '%',
            'state_topic': self.get_discovery_topic(device_id, 'storage'),
            'value_template': '{{ value_json.used_percent }}',
            'unique_id': self.get_slug(device_id, 'storage_used_percent'),
        }
        components[self.get_slug(device_id, 'storage_total')] = {
            'name': 'Storage Total',
            'platform': 'sensor',
            'icon': 'mdi:micro-sd',
            'unit_of_measurement': 'GB',
            'state_topic': self.get_discovery_topic(device_id, 'storage'),
            'value_template': '{{ value_json.total }}',
            'unique_id': self.get_slug(device_id, 'storage_total'),
        }
        components[self.get_slug(device_id, 'storage_used')] = {
            'name': 'Storage Used',
            'platform': 'sensor',
            'icon': 'mdi:micro-sd',
            'unit_of_measurement': 'GB',
            'state_topic': self.get_discovery_topic(device_id, 'storage'),
            'value_template': '{{ value_json.used }}',
            'unique_id': self.get_slug(device_id, 'storage_used'),
        }
        components[self.get_slug(device_id, 'last_update')] = {
            'name': 'Last Update',
            'platform': 'sensor',
            'device_class': 'timestamp',
            'entity_category': 'diagnostic',
            'state_topic': device['state_topic'],
            'value_template': '{{ value_json.last_update }}',
            'unique_id': self.get_slug(device_id, 'last_update'),
        }


        # since we always add at least `motion`, this should always be true
        if len(components) > 0:
            device['components'] = components

    def send_device_discovery(self, device_id):
        device = self.devices[device_id]
        self.mqttc.publish(self.get_discovery_topic(device_id, 'config'), json.dumps(device), retain=True)

    def refresh_all_devices(self):
        self.logger.info(f'Refreshing storage info for all devices (every {self.device_update_interval} sec)')

        # refresh devices starting with the device updated the longest time ago
        for each in sorted(self.devices.items(), key=lambda dt: (dt is None, dt)):
            # break loop if we are ending
            if not self.running:
                break
            device_id = each[0]

            self.refresh_device(device_id)

    def refresh_device(self, device_id):
        # don't refresh the device until it has been published in device discovery
        # and we can tell because it will be `online`

        #if self.devices[device_id]['state']['status'] != 'online':
        #    return

        config = self.configs[device_id]

        result = self.amcrestc.get_device_storage_stats(device_id)
        if result and 'last_update' in result:
            self.devices[device_id]['storage'] = result

        self.configs[device_id]['last_update'] = datetime.now(ZoneInfo(self.timezone))
        self.devices[device_id]['state'] = {
            'status': 'online',
            'host': config['host'],
            'serial_number': config['serial_number'],
            'sw_version': config['software_version'],
            'last_update': config['last_update'].isoformat(),
        }

        self.update_service_device()
        self.publish_device(device_id)

    def publish_device(self, device_id):
        for topic in ['state','availability','storage','motion','human','doorbell','event']:
            if topic in self.devices[device_id]:
                self.mqttc.publish(
                    self.get_discovery_topic(device_id,topic),
                    json.dumps(self.devices[device_id][topic]) if isinstance(self.devices[device_id][topic], dict) else self.devices[device_id][topic],
                    retain=True
                )

    def handle_service_message(self, attribute, message):
        match attribute:
            case 'device_refresh':
                self.device_update_interval = message
                self.logger.info(f'Updated UPDATE_INTERVAL to be {message}')
            case _:
                self.logger.info(f'IGNORED UNRECOGNIZED amcrest-service MESSAGE for {attribute}: {message}')
                return

        self.update_service_device()

    def send_command(self, device_id, data):
        caps = self.convert_attributes_to_capabilities(data)
        sku = self.devices[device_id]['device']['model']

        self.logger.debug(f'COMMAND {device_id} = {caps}')

        first = True
        for key in caps:
            if not first:
                time.sleep(1)
            self.logger.debug(f'CMD DEVICE {self.devices[device_id]['device']['name']} ({device_id}) {key} = {caps[key]}')
            self.amcrestc.send_command(device_id, sku, caps[key]['type'], caps[key]['instance'], caps[key]['value'])
            self.update_service_device()
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)

    def check_for_events(self):
        while device_event := self.amcrestc.get_next_event():
            if 'device_id' not in device_event:
                self.logger(f'Got event, but missing device_id: {device_event}')
                continue
            device_id = device_event['device_id']
            event = device_event['event']
            payload = device_event['payload']
            device = self.devices[device_id]

            self.logger.info(f'Got event for {device_id}: {event} {payload}')
            # if one of our known sensors
            if event in ['motion','human','doorbell']:
                device[event] = payload
            # otherwise, just store generically
            else:
                device['event'] = f'{event}: {payload}'

            self.refresh_device(device_id)


    # main loop
    async def main_loop(self):
        try:
            await self.setup_devices()
        except:
            self.running = False

        loop = asyncio.get_running_loop()
        tasks = [
            asyncio.create_task(self.device_loop()),
            asyncio.create_task(self.collect_events()),
            asyncio.create_task(self.process_events()),
        ]

        for signame in {'SIGINT','SIGTERM'}:
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda: asyncio.create_task(self._handle_sigterm(loop, tasks))
            )

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as err:
            self.logger.error(f'main_loop: {err}')
            self.running = False

    async def device_loop(self):
        while self.running == True:
            try:
                self.refresh_all_devices()
                await asyncio.sleep(self.device_update_interval)
            except Exception as err:
                self.logger.error('device_loop: {err}')
                self.running = False

    async def collect_events(self):
        while self.running == True:
            try:
               await self.amcrestc.collect_all_device_events()
            except Exception as err:
                self.logger.error(f'collect_events: {err}')
                self.running = False

    async def process_events(self):
        while self.running == True:
            try:
                self.check_for_events()
                await asyncio.sleep(1)
            except Exception as err:
                self.logger.error(f'process_events: {err}')
                self.running = False
