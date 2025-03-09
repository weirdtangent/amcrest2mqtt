import asyncio
from datetime import datetime
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
        self.running = False
        self.logger = logging.getLogger(__name__)

        self.mqttc = None
        self.mqtt_connect_time = None

        self.config = config
        self.mqtt_config = config['mqtt']
        self.amcrest_config = config['amcrest']
        self.timezone = config['timezone']
        self.version = config['version']

        self.storage_update_interval = config['amcrest'].get('storage_update_interval', 900)
        self.snapshot_update_interval = config['amcrest'].get('snapshot_update_interval', 300)
        self.discovery_complete = False

        self.client_id = self.get_new_client_id()
        self.service_name = self.mqtt_config['prefix'] + ' service'
        self.service_slug = self.mqtt_config['prefix'] + '-service'

        self.configs = {}
        self.states = {}

    def __enter__(self):
        self.mqttc_create()
        self.amcrestc = amcrest_api.AmcrestAPI(self.config)
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        self.logger.info('Exiting gracefully')

        if self.mqttc is not None and self.mqttc.is_connected():
            self.mqttc.disconnect()
        else:
            self.logger.info('Lost connection to MQTT')

    # MQTT Functions ------------------------------------------------------------------------------

    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            self.logger.error(f'MQTT CONNECTION ISSUE ({rc})')
            exit()
        self.logger.info(f'MQTT connected as {self.client_id}')
        client.subscribe(self.get_device_sub_topic())
        client.subscribe(self.get_attribute_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        self.logger.info('MQTT connection closed')

        if self.running and time.time() > self.mqtt_connect_time + 10:
            # lets use a new client_id for a reconnect
            self.client_id = self.get_new_client_id()
            self.mqttc_create()
        else:
            exit()

    def mqtt_on_log(self, client, userdata, paho_log_level, msg):
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            self.logger.error(f'MQTT LOG: {msg}')
        elif paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            self.logger.warn(f'MQTT LOG: {msg}')

    def mqtt_on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            payload = msg.payload.decode('utf-8')
        except:
            self.logger.error('Failed to understand MQTT message, ignoring')
            return

        # we might get:
        #   */service/set
        #   */service/set/attribute
        #   */device/component/set
        #   */device/component/set/attribute
        components = topic.split('/')

        # handle this message if it's for us, otherwise pass along to amcrest API
        if components[-2] == self.get_component_slug('service'):
            self.handle_service_message(None, payload)
        elif components[-3] == self.get_component_slug('service'):
            self.handle_service_message(components[-1], payload)
        else:
            if components[-1] == 'set':
                vendor, device_id = components[-2].split('-')
            elif components[-2] == 'set':
                vendor, device_id = components[-3].split('-')
            else:
                self.logger.error(f'UNKNOWN MQTT MESSAGE STRUCTURE: {topic}')
                return

            # of course, we only care about our 'amcrest-<serial>' messages
            if vendor != 'amcrest':
                return

            # ok, it's for us, lets announce it
            self.logger.debug(f'Incoming MQTT message for {topic} - {payload}')

            # if we only got back a scalar value, lets turn it into a dict with
            # the attribute name after `/set/` in the command topic
            if not isinstance(payload, dict) and attribute:
                payload = { attribute: payload }

            # if we just started, we might get messages immediately, lets
            # wait up to 3 min for devices to show up before we ignore the message
            checks = 0
            while device_id not in self.states:
                checks += 1
                # we'll try for 3 min, and then give up
                if checks > 36:
                    self.logger.warn(f"Got MQTT message for a device we don't know: {device_id}")
                    return
                time.sleep(5)

            self.logger.info(f'Got MQTT message for: {self.states[device_id]["device"]["name"]} - {payload}')

            # ok, lets format the device_id (not needed) and send to amcrest
            self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)
        self.logger.debug(f'MQTT SUBSCRIBED: reason_codes - {'; '.join(rc_list)}')

    # MQTT Helpers --------------------------------------------------------------------------------

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

        # will_set for service device
        self.mqttc.will_set(self.get_discovery_topic('service', 'availability'), payload="offline", qos=self.mqtt_config['qos'], retain=True)

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

    # MQTT Topics ---------------------------------------------------------------------------------

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

    def get_discovery_topic(self, device_id, topic):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/{topic}"
        return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/{topic}"

    def get_discovery_subtopic(self, device_id, topic, subtopic):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/{topic}/{subtopic}"
        return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/{topic}/{subtopic}"

    # Service Device ------------------------------------------------------------------------------

    def publish_service_state(self):
        if 'service' not in self.states:
            self.states['service'] = {
                'availability': 'online',
                'state': { 'state': 'ON' },
                'intervals': {},
            }

        service_states = self.states['service']

        # update states
        service_states['state'] = {
            'state': 'ON',
        }
        service_states['intervals'] = {
            'storage_refresh': self.storage_update_interval,
            'snapshot_refresh': self.snapshot_update_interval,
        }

        for topic in ['state','availability','intervals']:
            if topic in service_states:
                payload = json.dumps(service_states[topic]) if isinstance(service_states[topic], dict) else service_states[topic]
                self.mqttc.publish(self.get_discovery_topic('service', topic), payload, qos=self.mqtt_config['qos'], retain=True)

    def publish_service_device(self):
        state_topic = self.get_discovery_topic('service', 'state')
        command_topic = self.get_discovery_topic('service', 'set')
        availability_topic = self.get_discovery_topic('service', 'availability')

        self.mqttc.publish(
            self.get_discovery_topic('service','config'),
            json.dumps({
                'qos': self.mqtt_config['qos'],
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
                        'payload_on': 'ON',
                        'payload_off': 'OFF',
                        'icon': 'mdi:language-python',
                        'state_topic': state_topic,
                        'value_template': '{{ value_json.state }}',
                        'unique_id': 'amcrest_service_status',
                    },
                    self.service_slug + '_storage_refresh': {
                        'name': 'Storage Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 10,
                        'max': 3600,
                        'state_topic': self.get_discovery_topic('service', 'intervals'),
                        'command_topic': self.get_command_topic('service', 'storage_refresh'),
                        'value_template': '{{ value_json.storage_refresh }}',
                        'unique_id': 'amcrest_service_storage_refresh',
                    },
                    self.service_slug + '_snapshot_refresh': {
                        'name': 'Snapshot Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 10,
                        'max': 3600,
                        'state_topic': self.get_discovery_topic('service', 'intervals'),
                        'command_topic': self.get_command_topic('service', 'snapshot_refresh'),
                        'value_template': '{{ value_json.snapshot_refresh }}',
                        'unique_id': 'amcrest_service_snapshot_refresh',
                    },
                },
            }),
            qos=self.mqtt_config['qos'],
            retain=True
        )

    # Amcrest Helpers -----------------------------------------------------------------------------

    # setup devices -------------------------------------------------------------------------------

    async def setup_devices(self):
        self.logger.info(f'Setup devices')

        devices = await self.amcrestc.connect_to_devices()
        self.logger.info(f'Connected to: {list(devices.keys())}')

        self.publish_service_device()
        for device_id in devices:
            config = devices[device_id]

            if 'device_type' in config:
                first = False
                if device_id not in self.configs:
                    first = True
                    self.configs[device_id] = {}
                    self.states[device_id] = config
                    self.configs[device_id]['qos'] = self.mqtt_config['qos']
                    self.configs[device_id]['state_topic'] = self.get_discovery_topic(device_id, 'state')
                    self.configs[device_id]['availability_topic'] = self.get_discovery_topic('service', 'availability')
                    self.configs[device_id]['command_topic'] = self.get_discovery_topic(device_id, 'set')

                self.configs[device_id]['device'] = {
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
                self.configs[device_id]['origin'] = {
                    'name': self.service_name,
                    'sw_version': self.version,
                    'support_url': 'https://github.com/weirdtangent/amcrest2mqtt',
                }

                # setup initial satte
                self.states[device_id]['state'] = {
                    'state': 'ON',
                    'last_update': None,
                    'host': config['host'],
                    'serial_number': config['serial_number'],
                    'sw_version': config['software_version'],
                }

                self.add_components_to_device(device_id)

                if first:
                    self.logger.info(f'Adding device: "{config['device_name']}" [Amcrest {config["device_type"]}] ({device_id})')
                    self.publish_device_discovery(device_id)
                else:
                    self.logger.debug(f'Updated device: {self.configs[device_id]['device']['name']}')

            else:
                if first_time_through:
                    self.logger.info(f'Saw device, but not supported yet: "{config["device_name"]}" [amcrest {config["device_type"]}] ({device_id})')

        # lets log our first time through and then release the hounds
        if not self.discovery_complete:
            self.logger.info('Device setup and discovery is done')
            self.discovery_complete = True

    # add amcrest components to devices
    def add_components_to_device(self, device_id):
        device_config = self.configs[device_id]
        device_states = self.states[device_id]
        components = {}

        if device_states['is_doorbell']:
            doorbell_name = 'Doorbell' if device_states['device_name'] == 'Doorbell' else f'{device_states["device_name"]} Doorbell'
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
            device_states['doorbell'] = {}

        if device_states['is_ad410']:
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
            device_states['human'] = {}

        components[self.get_slug(device_id, 'camera')] = {
            'name': 'Camera',
            'platform': 'camera',
            'topic': self.get_discovery_subtopic(device_id, 'camera','snapshot'),
            'image_encoding': 'b64',
            'state_topic': device_config['state_topic'],
            'value_template': '{{ value_json.state }}',
            'unique_id': self.get_slug(device_id, 'camera'),
        }
        if 'webrtc' in self.amcrest_config:
            webrtc_config = self.amcrest_config['webrtc']
            rtc_host = webrtc_config['host']
            rtc_port = webrtc_config['port']
            rtc_link = webrtc_config['link']
            rtc_source = webrtc_config['sources'].pop(0)
            rtc_url = f'http://{rtc_host}:{rtc_port}/{rtc_link}?src={rtc_source}'
            device_config['device']['configuration_url'] = rtc_url
        device_states['camera'] = {'snapshot': None}

        components[self.get_slug(device_id, 'motion')] = {
            'name': 'Motion',
            'platform': 'binary_sensor',
            'payload_on': 'on',
            'payload_off': 'off',
            'device_class': 'motion',
            'state_topic': self.get_discovery_topic(device_id, 'motion'),
            'unique_id': self.get_slug(device_id, 'motion'),
        }
        device_states['motion'] = {}

        components[self.get_slug(device_id, 'version')] = {
            'name': 'Version',
            'platform': 'sensor',
            'icon': 'mdi:package-up',
            'state_topic': device_config['state_topic'],
            'value_template': '{{ value_json.sw_version }}',
            'entity_category': 'diagnostic',
            'unique_id': self.get_slug(device_id, 'sw_version'),
        }

        components[self.get_slug(device_id, 'serial_number')] = {
            'name': 'Serial Number',
            'platform': 'sensor',
            'icon': 'mdi:identifier',
            'state_topic': device_config['state_topic'],
            'value_template': '{{ value_json.serial_number }}',
            'entity_category': 'diagnostic',
            'unique_id': self.get_slug(device_id, 'serial_number'),
        }

        components[self.get_slug(device_id, 'host')] = {
            'name': 'Host',
            'platform': 'sensor',
            'icon': 'mdi:ip-network',
            'state_topic': device_config['state_topic'],
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
        device_states['event'] = {}
        device_states['recording'] = {}

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
        device_states['storage'] = {}

        components[self.get_slug(device_id, 'last_update')] = {
            'name': 'Last Update',
            'platform': 'sensor',
            'device_class': 'timestamp',
            'entity_category': 'diagnostic',
            'state_topic': device_config['state_topic'],
            'value_template': '{{ value_json.last_update }}',
            'unique_id': self.get_slug(device_id, 'last_update'),
        }

        device_config['components'] = components

    def publish_device_state(self, device_id):
        device_states = self.states[device_id]

        for topic in ['state','storage','motion','human','doorbell','event','recording']:
            if topic in device_states:
                payload = json.dumps(device_states[topic]) if isinstance(device_states[topic], dict) else device_states[topic]
                self.mqttc.publish(self.get_discovery_topic(device_id, topic), payload, qos=self.mqtt_config['qos'], retain=True)

        if 'snapshot' in device_states['camera'] and device_states['camera']['snapshot'] is not None:
            payload = device_states['camera']['snapshot']
            result = self.mqttc.publish(self.get_discovery_subtopic(device_id, 'camera','snapshot'), payload, qos=self.mqtt_config['qos'], retain=True)

    def publish_device_discovery(self, device_id):
        device_config = self.configs[device_id]
        payload = json.dumps(device_config)

        self.mqttc.publish(self.get_discovery_topic(device_id, 'config'), payload, qos=self.mqtt_config['qos'], retain=True)

     # refresh * all devices -----------------------------------------------------------------------

    def refresh_storage_all_devices(self):
        self.logger.info(f'Refreshing storage info for all devices (every {self.storage_update_interval} sec)')

        for device_id in self.configs:
            if not self.running: break
            device_states = self.states[device_id]

            # get the storage info, pull out last_update and save that to the device state
            storage = self.amcrestc.get_device_storage_stats(device_id)
            device_states['state']['last_update'] = storage.pop('last_update', None)
            device_states['storage'] = storage

            self.publish_service_state()
            self.publish_device_state(device_id)

    def refresh_snapshot_all_devices(self):
        self.logger.info(f'Collecting snapshots for all devices (every {self.snapshot_update_interval} sec)')

        for device_id in self.configs:
            if not self.running: break
            self.refresh_snapshot(device_id)

    def refresh_snapshot(self, device_id):
        device_states = self.states[device_id]
        image = self.amcrestc.get_snapshot(device_id)

        # only store and send to MQTT if the image has changed
        if device_states['camera']['snapshot'] is None or device_states['camera']['snapshot'] != image:
            device_states['camera']['snapshot'] = image
            self.publish_service_state()
            self.publish_device_state(device_id)

    # send command to Amcrest  --------------------------------------------------------------------

    def send_command(self, device_id, data):
        device_config = self.configs[device_id]
        device_states = self.states[device_id]

        self.logger.info(f'COMMAND {device_states["device_name"]} = {data}')

        if data == 'PRESS':
            pass
        else:
            self.logger.error(f'We got a command ({data}), but do not know what to do')

    def handle_service_message(self, attribute, message):
        match attribute:
            case 'storage_refresh':
                self.storage_update_interval = message
                self.logger.info(f'Updated STORAGE_REFRESH_INTERVAL to be {message}')
            case 'snapshot_refresh':
                self.snapshot_update_interval = message
                self.logger.info(f'Updated SNAPSHOT_REFRESH_INTERVAL to be {message}')
            case _:
                self.logger.info(f'IGNORED UNRECOGNIZED amcrest-service MESSAGE for {attribute}: {message}')
                return

        self.publish_service_state()

    # collect events and then check queue of events -----------------------------------------------

    async def collect_all_device_events(self):
        await self.amcrestc.collect_all_device_events()

    def check_for_events(self):
        while device_event := self.amcrestc.get_next_event():
            if device_event is None:
                break
            if 'device_id' not in device_event:
                self.logger(f'Got event, but missing device_id: {device_event}')
                continue

            device_id = device_event['device_id']
            event = device_event['event']
            payload = device_event['payload']

            device_states = self.states[device_id]

            # if one of our known sensors
            if event in ['motion','human','doorbell','recording']:
                self.logger.info(f'Got event for {device_states["device_name"]}: {event}')
                device_states[event] = payload

                # any of these could mean a new snapshot is available early, lets try to grab it
                self.logger.debug(f'Refreshing snapshot for "{device_states["device_name"]}" early because of event')
                self.refresh_snapshot(device_id)
            else:
                self.logger.info(f'Got "other" event for "{device_states["device_name"]}": {event} {payload}')
                device_states['event'] = event

            self.publish_device_state(device_id)

    # async loops and main loop -------------------------------------------------------------------

    async def _handle_signals(self, signame, loop):
        self.running = False
        self.logger.warn(f'{signame} received, waiting for tasks to cancel...')

        for task in asyncio.all_tasks():
            if not task.done(): task.cancel(f'{signame} received')

    async def collect_storage_info(self):
        while self.running == True:
            self.refresh_storage_all_devices()
            await asyncio.sleep(self.storage_update_interval)

    async def collect_events(self):
        while self.running == True:
            await self.collect_all_device_events()
            await asyncio.sleep(1)

    async def check_event_queue(self):
        while self.running == True:
            self.check_for_events()
            await asyncio.sleep(1)

    async def collect_snapshots(self):
        while self.running == True:
            await self.amcrestc.collect_all_device_snapshots()
            self.refresh_snapshot_all_devices()
            await asyncio.sleep(self.snapshot_update_interval)

    # main loop
    async def main_loop(self):
        await self.setup_devices()

        loop = asyncio.get_running_loop()
        tasks = [
            asyncio.create_task(self.collect_storage_info()),
            asyncio.create_task(self.collect_events()),
            asyncio.create_task(self.check_event_queue()),
            asyncio.create_task(self.collect_snapshots()),
        ]

        # setup signal handling for tasks
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(self._handle_signals(sig.name, loop))
            )

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            exit(1)
        except Exception as err:
            self.running = False
            self.log.error(f'Caught exception: {err}')