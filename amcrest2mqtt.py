from amcrest import AmcrestCamera, AmcrestError
import argparse
import asyncio
from datetime import datetime, timezone
from json import dumps
import paho.mqtt.client as mqtt
import os
import signal
from slugify import slugify
import ssl
import sys
from threading import Timer
import time
import yaml
from zoneinfo import ZoneInfo

is_exiting = False
mqtt_client = None
config = { 'timezone': 'America/New_York' }
devices = {}

# Helper functions and callbacks
def log(msg, level='INFO'):
    ts = datetime.now(tz=ZoneInfo(config['timezone'])).strftime('%Y-%m-%d %H:%M:%S')
    if len(msg) > 20480:
        raise ValueError('Log message exceeds max length')
    if level != "DEBUG" or os.getenv('DEBUG'):
        print(f'{ts} [{level}] {msg}')

def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile("./VERSION"):
        return read_file("./VERSION")

    return read_file("../VERSION")

def to_gb(total):
    return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))

def signal_handler(sig, frame):
    # exit immediately upon receiving a second SIGINT
    global is_exiting

    if is_exiting:
        os._exit(1)

    is_exiting = True
    exit_gracefully(0)

def exit_gracefully(rc, skip_mqtt=False):
    log("Exiting app...")

    if mqtt_client is not None and mqtt_client.is_connected() and skip_mqtt == False:
        # set cameras offline
        for host in config['amcrest']['hosts']:
            mqtt_publish(devices[host]["topics"]["status"], "offline", exit_on_error=False)
        # set broker offline
        mqtt_publish(f'{config["mqtt"]["prefix"]}/{via_device}/availability', "offline")
        mqtt_publish(f'{config["mqtt"]["prefix"]}/{via_device}/status', "offline")

        mqtt_client.disconnect()

    # Use os._exit instead of sys.exit to ensure an MQTT disconnect event causes the program to exit correctly as they
    # occur on a separate thread
    os._exit(rc)

# MQTT setup
def mqtt_connect():
    global mqtt_client

    if config['mqtt']['username'] is None:
        log("Missing env vari: MQTT_USERNAME or mqtt.username in config", level="ERROR")
        sys.exit(1)

    mqtt_client = mqtt.Client(
      mqtt.CallbackAPIVersion.VERSION1,
      client_id=f'{config["mqtt"]["prefix"]}_broker',
      clean_session=False
    )
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect

    # send "will_set" for the broker and each connected camera
    mqtt_client.will_set(f'{config["mqtt"]["prefix"]}/{via_device}', payload="offline", qos=config['mqtt']['qos'], retain=True)
    for host in config['amcrest']['hosts']:
        mqtt_client.will_set(devices[host]["topics"]["status"], payload="offline", qos=config['mqtt']['qos'], retain=True)

    if config['mqtt']['tls_enabled']:
        log(f"Setting up MQTT for TLS")
        if config['mqtt']['tls_ca_cert'] is None:
            log("Missing env var: MQTT_TLS_CA_CERT or mqtt.tls_ca_cert in config", level="ERROR")
            sys.exit(1)
        if config['mqtt']['tls_cert'] is None:
            log("Missing env var: MQTT_TLS_CERT or mqtt.tls_cert in config", level="ERROR")
            sys.exit(1)
        if config['mqtt']['tls_cert'] is None:
            log("Missing env var: MQTT_TLS_KEY or mqtt.tls_key in config", level="ERROR")
            sys.exit(1)
        mqtt_client.tls_set(
            ca_certs=config['mqtt']['tls_ca_cert'],
            certfile=config['mqtt']['tls_cert'],
            keyfile=config['mqtt']['tls_key'],
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
        )
    else:
        mqtt_client.username_pw_set(config['mqtt']['username'], password=config['mqtt']['password'])

    try:
        mqtt_client.connect(
            config['mqtt']['host'],
            port=config['mqtt']['port'],
            keepalive=60
        )
        mqtt_client.loop_start()
    except ConnectionError as error:
        log(f"Could not connect to MQTT server: {error}", level="ERROR")
        sys.exit(1)

def on_mqtt_connect(mqtt_client, userdata, flags, rc):
    if rc != 0:
        log(f"MQTT Connection Issue: {rc}", level="ERROR")
        exit_gracefully(rc, skip_mqtt=True)
    log(f"MQTT Connected", level="INFO")

def on_mqtt_disconnect(mqtt_client, userdata, rc):
    if rc != 0:
        log(f"MQTT connection failed: {rc}", level="ERROR")
    else:
        log(f"MQTT connection closed successfully", level="INFO")
    exit_gracefully(rc, skip_mqtt=True)

def mqtt_publish(topic, payload, exit_on_error=True, json=False):
    msg = mqtt_client.publish(
      topic, payload=(dumps(payload) if json else payload), qos=config['mqtt']['qos'], retain=True
    )

    if msg.rc == mqtt.MQTT_ERR_SUCCESS:
        msg.wait_for_publish(2)
        return

    log(f"Error publishing MQTT message: {mqtt.error_string(msg.rc)}", level="ERROR")

    if exit_on_error:
        exit_gracefully(msg.rc, skip_mqtt=True)

# Amcrest Devices
def get_device(amcrest_host, amcrest_port, amcrest_username, amcrest_password, device_name):
    log(f"Connecting to device and getting details for {amcrest_host}...")
    camera = AmcrestCamera(
        amcrest_host, amcrest_port, amcrest_username, amcrest_password
    ).camera

    try:
        device_type = camera.device_type.replace("type=", "").strip()
        is_ad110 = device_type == "AD110"
        is_ad410 = device_type == "AD410"
        is_doorbell = is_ad110 or is_ad410
        serial_number = camera.serial_number

        if not isinstance(serial_number, str):
            log(f"Error fetching serial number for {amcrest_host}", level="ERROR")
            exit_gracefully(1)

        sw_version = camera.software_information[0].replace("version=", "").strip()
        build_version = camera.software_information[1].strip()
        amcrest_version = f"{sw_version} ({build_version})"
        device_slug = slugify(device_name, separator="_")
        vendor = camera.vendor_information
        hardware_version = camera.hardware_version
    except AmcrestError as error:
        log(f"Error fetching camera details for {amcrest_host}", level="ERROR")
        exit_gracefully(1)

    log(f"  Vendor: {camera.vendor_information}")
    log(f"  Device name: {device_name}")
    log(f"  Device type: {device_type}")
    log(f"  Serial number: {serial_number}")
    log(f"  Software version: {amcrest_version}")
    log(f"  Hardware version: {camera.hardware_version}")

    home_assistant_prefix = config['mqtt']['home_assistant_prefix']

    return {
      "camera": camera,
      "config": {
        "amcrest_host": amcrest_host,
        "device_name": device_name,
        "device_type": device_type,
        "device_slug": device_slug,
        "device_class": camera.device_class,
        "is_ad110": is_ad110,
        "is_ad410": is_ad410,
        "is_doorbell": is_doorbell,
        "serial_number": serial_number,
        "amcrest_version": amcrest_version,
        "hardware_version": hardware_version,
        "vendor": vendor,
      },
      "telemetry": {
      },
      "topics": {
        "config": f'{config["mqtt"]["prefix"]}/{serial_number}/config',
        "status": f'{config["mqtt"]["prefix"]}/{serial_number}/status',
        "telemetry": f'{config["mqtt"]["prefix"]}/{serial_number}/telemetry',
        "event": f'{config["mqtt"]["prefix"]}/{serial_number}/event',
        "motion": f'{config["mqtt"]["prefix"]}/{serial_number}/motion',
        "doorbell": f'{config["mqtt"]["prefix"]}/{serial_number}/doorbell',
        "human": f'{config["mqtt"]["prefix"]}/{serial_number}/human',
        "storage_used": f'{config["mqtt"]["prefix"]}/{serial_number}/storage/used',
        "storage_used_percent": f'{config["mqtt"]["prefix"]}/{serial_number}/storage/used_percent',
        "storage_total": f'{config["mqtt"]["prefix"]}/{serial_number}/storage/total',
        "home_assistant": {
          "doorbell": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/doorbell/config",
          "human": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/human/config",
          "motion": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/motion/config",
          "storage_used": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/storage_used/config",
          "storage_used_percent": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/storage_used_percent/config",
          "storage_total": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/storage_total/config",
          "version": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/version/config",
          "host": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/host/config",
          "serial_number": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/serial_number/config",
        },
      },
    }

# MQTT messages
def send_broker_discovery():
    mqtt_publish(f'{config["mqtt"]["home_assistant_prefix"]}/sensor/{via_device}/broker/config', {
        "availability_topic": f'{config["mqtt"]["prefix"]}/{via_device}/availability',
        "state_topic": f'{config["mqtt"]["prefix"]}/{via_device}/status',
        "qos": config['mqtt']['qos'],
        "device": {
            "name": 'amcrest2mqtt broker',
            "identifiers": via_device,
        },
        "icon": 'mdi:language-python',
        "unique_id": via_device,
        "name": "amcrest2mqtt broker",
        },
        json=True,
    )

def send_device_discovery(device):
    vendor = device["config"]["vendor"]
    device_name = device["config"]["device_name"]
    device_type = device["config"]["device_type"]
    device_slug = device["config"]["device_slug"]
    serial_number = device["config"]["serial_number"]
    amcrest_version = device["config"]["amcrest_version"]
    hw_version = device["config"]["hardware_version"]

    base_config = {
      "availability_topic": device["topics"]["status"],
      "qos": config['mqtt']['qos'],
      "device": {
        "name": device_name,
        "manufacturer": vendor,
        "model": device_type,
        "identifiers": serial_number,
        "sw_version": amcrest_version,
        "hw_version": hw_version,
        "via_device": via_device,
      },
    }

    if device["config"]["is_doorbell"]:
        doorbell_name = "Doorbell" if device_name == "Doorbell" else f"{device_name} Doorbell"

        mqtt_publish(
          device["topics"]["home_assistant"]["doorbell"],
          base_config
          | {
              "state_topic": device["topics"]["doorbell"],
              "payload_on": "on",
              "payload_off": "off",
              "icon": "mdi:doorbell",
              "name": doorbell_name,
              "unique_id": f"{serial_number}.doorbell",
          },
          json=True,
        )

    if device["config"]["is_ad410"]:
        mqtt_publish(
          device["topics"]["home_assistant"]["human"],
          base_config
          | {
              "state_topic": device["topics"]["human"],
              "payload_on": "on",
              "payload_off": "off",
              "device_class": "motion",
              "name": "Human",
              "unique_id": f"{serial_number}.human",
          },
          json=True,
        )

    mqtt_publish(
      device["topics"]["home_assistant"]["motion"],
      base_config
      | {
          "state_topic": device["topics"]["motion"],
          "payload_on": "on",
          "payload_off": "off",
          "device_class": "motion",
          "name": "Motion",
          "unique_id": f"{serial_number}.motion",
      },
      json=True,
    )

    mqtt_publish(
      device["topics"]["home_assistant"]["version"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.sw_version }}",
          "icon": "mdi:package-up",
          "name": "Version",
          "unique_id": f"{serial_number}.version",
          "entity_category": "diagnostic",
          "enabled_by_default": False
      },
      json=True,
    )

    mqtt_publish(
      device["topics"]["home_assistant"]["serial_number"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.serial_number }}",
          "icon": "mdi:alphabetical-variant",
          "name": "Serial Number",
          "unique_id": f"{serial_number}.serial_number",
          "entity_category": "diagnostic",
          "enabled_by_default": False
      },
      json=True,
    )

    mqtt_publish(
      device["topics"]["home_assistant"]["host"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.host }}",
          "icon": "mdi:ip-network",
          "name": "Host",
          "unique_id": f"{serial_number}.host",
          "entity_category": "diagnostic",
          "enabled_by_default": False
        },
        json=True,
    )

    if config['amcrest']['storage_poll_interval'] > 0:
        mqtt_publish(
          device["topics"]["home_assistant"]["storage_used_percent"],
          base_config
          | {
              "state_topic": device["topics"]["storage_used_percent"],
              "unit_of_measurement": "%",
              "icon": "mdi:micro-sd",
              "name": f"Storage Used %",
              "object_id": f"{device_slug}_storage_used_percent",
              "unique_id": f"{serial_number}.storage_used_percent",
              "entity_category": "diagnostic",
          },
          json=True,
        )

        mqtt_publish(
          device["topics"]["home_assistant"]["storage_used"],
          base_config
          | {
              "state_topic": device["topics"]["storage_used"],
              "unit_of_measurement": "GB",
              "icon": "mdi:micro-sd",
              "name": "Storage Used",
              "unique_id": f"{serial_number}.storage_used",
              "entity_category": "diagnostic",
          },
          json=True,
        )

        mqtt_publish(
          device["topics"]["home_assistant"]["storage_total"],
          base_config
          | {
              "state_topic": device["topics"]["storage_total"],
              "unit_of_measurement": "GB",
              "icon": "mdi:micro-sd",
              "name": "Storage Total",
              "unique_id": f"{serial_number}.storage_total",
              "entity_category": "diagnostic",
          },
          json=True,
        )

def refresh_broker():
    Timer(60, refresh_broker).start()
    log('Refreshing amcrest2mqtt broker, every 60 sec')
    mqtt_publish(f'{config["mqtt"]["prefix"]}/{via_device}/availability', 'online')
    mqtt_publish(f'{config["mqtt"]["prefix"]}/{via_device}/status', 'online')
    mqtt_publish(f'{config["mqtt"]["prefix"]}/{via_device}/config', {
        'device_name': 'amcrest2mqtt broker',
        'sw_version': version,
        'origin': {
            'name': 'amcrest2mqtt broker',
            'sw_version': version,
            'url': 'https://github.com/weirdtangent/amcrest2mqtt',
        },
    }, json=True)

def refresh_devices():
    for host in config['amcrest']['hosts']:
        refresh_device(devices[host])

def refresh_device(device):
    mqtt_publish(device['topics']['status'], 'online')
    mqtt_publish(device['topics']['config'], {
        'device_type': device['config']['device_type'],
        'device_name': device['config']['device_name'],
        'sw_version': device['config']['amcrest_version'],
        'hw_version': device['config']['hardware_version'],
        'serial_number': device['config']['serial_number'],
        'host': device['config']['amcrest_host'],
        'configuration_url': 'http://' + device['config']['amcrest_host'] + '/',
        'origin': {
            'name': 'amcrest2mqtt broker',
            'sw_version': version,
            'url': 'https://github.com/weirdtangent/amcrest2mqtt',
        },
    }, json=True)
    mqtt_publish(device['topics']['telemetry'],
        dumps(device['telemetry']),
    json=True)

def refresh_storage_sensors():
    Timer(config['amcrest']['storage_poll_interval'], refresh_storage_sensors).start()
    log(f'Fetching storage sensors for {config["amcrest"]["host_count"]} host(s) (every {config["amcrest"]["storage_poll_interval"]} secs)')

    for host in config['amcrest']['hosts']:
        device = devices[host]
        topics = device["topics"]
        try:
            storage = device["camera"].storage_all

            mqtt_publish(topics["storage_used_percent"], str(storage["used_percent"]))
            mqtt_publish(topics["storage_used"], to_gb(storage["used"]))
            mqtt_publish(topics["storage_total"], to_gb(storage["total"]))
        except AmcrestError as error:
            log(f"Error fetching storage information for {host}: {error}", level="WARNING")


# cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    "-c",
    "--config",
    required=False,
    help="Directory holding config.yaml or full path to config file",
)
args = argparser.parse_args()

# load config file
configpath = args.config
if configpath:
    if not configpath.endswith(".yaml"):
        if not configpath.endswith("/"):
            configpath += "/"
        configpath += "config.yaml"
    log(f"Trying to load config file {configpath}")
    with open(configpath) as file:
        config = yaml.safe_load(file)
# or check env vars
else:
    log(f"INFO:root:No config file specified, checking ENV")
    config = {
        'mqtt': {
            'host': os.getenv("MQTT_HOST") or 'localhost',
            'port': int(os.getenv("MQTT_PORT") or 1883),
            'username': os.getenv("MQTT_USERNAME"),
            'password': os.getenv("MQTT_PASSWORD"),  # can be None
            'qos': int(os.getenv("MQTT_QOS") or 0),
            'prefix': os.getenv("MQTT_PREFIX") or 'amcrest2mqtt',
            'home_assistant_prefix': os.getenv("MQTT_HOME_ASSISTANT_PREFIX") or "homeassistant",
            'tls_enabled': os.getenv("MQTT_TLS_ENABLED") == "true",
            'tls_ca_cert': os.getenv("MQTT_TLS_CA_CERT"),
            'tls_cert': os.getenv("MQTT_TLS_CERT"),
            'tls_key': os.getenv("MQTT_TLS_KEY"),
        },
        'amcrest': {
            'hosts': os.getenv("AMCREST_HOSTS"),
            'names': os.getenv("AMCREST_NAMES"),
            'port': int(os.getenv("AMCREST_PORT") or 80),
            'username': os.getenv("AMCREST_USERNAME") or "admin",
            'password': os.getenv("AMCREST_PASSWORD"),
            'storage_poll_interval': int(os.getenv("STORAGE_POLL_INTERVAL") or 3600),
        },
        'home_assistant': os.getenv("HOME_ASSISTANT") == "true",
        'debug': os.getenv("AMCREST_DEBUG") == "true",
        'timezone': os.getenv("TZ") or 'utc',
    }

# Exit if any of the required vars are not provided
if config['amcrest']['hosts'] is None:
    log("Missing env var: AMCREST_HOSTS or amcrest.hosts in config", level="ERROR")
    sys.exit(1)
config['amcrest']['host_count'] = len(config['amcrest']['hosts'])

if config['amcrest']['names'] is None:
    log("Missing env var: AMCREST_NAMES or amcrest.names in config", level="ERROR")
    sys.exit(1)
config['amcrest']['name_count'] = len(config['amcrest']['names'])

if config['amcrest']['host_count'] != config['amcrest']['name_count']:
    log("The AMCREST_HOSTS and AMCREST_NAMES must have the same number of space-delimited hosts/names", level="ERROR")
    sys.exit(1)
log(f"Found {config['amcrest']['host_count']} host(s) defined to monitor")

if config['amcrest']['password'] is None:
    log("Please set the AMCREST_PASSWORD environment variable", level="ERROR")
    sys.exit(1)

version = read_version()
via_device = config["mqtt"]["prefix"] + '-broker'
log(f"Starting: amcrest2mqtt v{version}")

# handle interruptions
signal.signal(signal.SIGINT, signal_handler)

# connect to each camera
amcrest_names = config['amcrest']['names']
for host in config['amcrest']['hosts']:
    name = amcrest_names.pop(0)
    log(f"Connecting host: {host} as {name}", level="INFO")
    devices[host] = get_device(host, config['amcrest']['port'], config['amcrest']['username'], config['amcrest']['password'], name)
log(f"Connecting to hosts done.", level="INFO")

# connect to MQTT service
mqtt_connect()

# configure broker and devices in Home Assistant
if config['home_assistant']:
    send_broker_discovery()
    for host in config['amcrest']['hosts']:
        send_device_discovery(devices[host])

refresh_broker()
refresh_devices()

# kick off storage refresh timer
if config['amcrest']['storage_poll_interval'] > 0:
    refresh_storage_sensors()

log(f"Listening for events on {config['amcrest']['host_count']} host(s)", level="DEBUG")

async def main():
    try:
        for host in config['amcrest']['hosts']:
            device = devices[host]
            device_config = device["config"]
            device_topics = device["topics"]
            async for code, payload in device["camera"].async_event_actions("All"):
                log(f"Event on {host} - {code}: {payload['action']}")
                if ((code == "ProfileAlarmTransmit" and device_config["is_ad110"])
                or (code == "VideoMotion" and not device_config["is_ad110"])):
                    motion_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(device_topics["motion"], motion_payload)
                    device[host]['telemetry']['last_motion_event'] = str(datetime.now(tz=ZoneInfo(config['timezone'])))
                elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                    human_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(device_topics["human"], human_payload)
                    device[host]['telemetry']['last_human_event'] = str(datetime.now(tz=ZoneInfo(config['timezone'])))
                elif code == "_DoTalkAction_":
                    doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                    mqtt_publish(device_topics["doorbell"], doorbell_payload)
                    device[host]['telemetry']['last_doorbell_event'] = str(datetime.now(tz=ZoneInfo(config['timezone'])))

                mqtt_publish(device_topics["event"], payload, json=True)
                refresh_device(device)

    except AmcrestError as error:
        log(f"Amcrest error while working on {host}: {AmcrestError}. Sleeping for 10 seconds.", level="ERROR")
        time.sleep(10)

asyncio.run(main())
