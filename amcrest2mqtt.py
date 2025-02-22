from slugify import slugify
from amcrest import AmcrestCamera, AmcrestError
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import os
import sys
import time
from json import dumps
import signal
from threading import Timer
import ssl
import asyncio

is_exiting = False
mqtt_client = None
devices = {}

# Read env variables
amcrest_hosts = os.getenv("AMCREST_HOSTS")
amcrest_port = int(os.getenv("AMCREST_PORT") or 80)
amcrest_username = os.getenv("AMCREST_USERNAME") or "admin"
amcrest_password = os.getenv("AMCREST_PASSWORD")

mqtt_qos = int(os.getenv("MQTT_QOS") or 0)

storage_poll_interval = int(os.getenv("STORAGE_POLL_INTERVAL") or 3600)
device_names = os.getenv("DEVICE_NAMES")

home_assistant = os.getenv("HOME_ASSISTANT") == "true"
home_assistant_prefix = os.getenv("HOME_ASSISTANT_PREFIX") or "homeassistant"

debug_mode = os.getenv("AMCREST_DEBUG") == "true"

# Helper functions and callbacks
def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile("./VERSION"):
        return read_file("./VERSION")

    return read_file("../VERSION")

def log(msg, level="INFO"):
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S")
    if level != "DEBUG" or debug_mode:
        print(f"{ts} [{level}] {msg}")

def mqtt_publish(topic, payload, exit_on_error=True, json=False):
    global mqtt_client, mqtt_qos

    msg = mqtt_client.publish(
      topic, payload=(dumps(payload) if json else payload), qos=mqtt_qos, retain=True
    )

    if msg.rc == mqtt.MQTT_ERR_SUCCESS:
        msg.wait_for_publish(2)
        return

    log(f"Error publishing MQTT message: {mqtt.error_string(msg.rc)}", level="ERROR")

    if exit_on_error:
        exit_gracefully(msg.rc, skip_mqtt=True)

def mqtt_connect():
    global mqtt_client, mqtt_qos

    mqtt_host = os.getenv("MQTT_HOST") or "localhost"
    mqtt_port = int(os.getenv("MQTT_PORT") or 1883)
    mqtt_username = os.getenv("MQTT_USERNAME")
    mqtt_password = os.getenv("MQTT_PASSWORD")  # can be None
    mqtt_tls_enabled = os.getenv("MQTT_TLS_ENABLED") == "true"
    mqtt_tls_ca_cert = os.getenv("MQTT_TLS_CA_CERT")
    mqtt_tls_cert = os.getenv("MQTT_TLS_CERT")
    mqtt_tls_key = os.getenv("MQTT_TLS_KEY")

    if mqtt_username is None:
        log("Please set the MQTT_USERNAME environment variable", level="ERROR")
        sys.exit(1)

    # Connect to MQTT
    mqtt_client = mqtt.Client(
      mqtt.CallbackAPIVersion.VERSION1,
      client_id=f"amcrest2mqtt_broker",
      clean_session=False
    )
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect

    # send "will_set" for each connected camera
    for host in hosts:
        mqtt_client.will_set(devices[host]["topics"]["status"], payload="offline", qos=mqtt_qos, retain=True)

    if mqtt_tls_enabled:
        log(f"Setting up MQTT for TLS")
        if mqtt_tls_ca_cert is None:
            log("Missing env var: MQTT_TLS_CA_CERT", level="ERROR")
            sys.exit(1)
        if mqtt_tls_cert is None:
            log("Missing env var: MQTT_TLS_CERT", level="ERROR")
            sys.exit(1)
        if mqtt_tls_cert is None:
            log("Missing env var: MQTT_TLS_KEY", level="ERROR")
            sys.exit(1)
        mqtt_client.tls_set(
            ca_certs=mqtt_tls_ca_cert,
            certfile=mqtt_tls_cert,
            keyfile=mqtt_tls_key,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
        )
    else:
        mqtt_client.username_pw_set(mqtt_username, password=mqtt_password)

    try:
        mqtt_client.connect(
            mqtt_host,
            port=mqtt_port,
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

def on_mqtt_disconnect(mqtt_client, userdata, flags, rc, properties):
    if rc != 0:
        log(f"MQTT connection failed: {rc}", level="ERROR")
    else:
        log(f"MQTT connection closed successfully", level="INFO")
    exit_gracefully(rc, skip_mqtt=True)

def exit_gracefully(rc, skip_mqtt=False):
    global hosts, devices, mqtt_client

    log("Exiting app...")

    if mqtt_client is not None and mqtt_client.is_connected() and skip_mqtt == False:
        for host in hosts:
            mqtt_publish(devices[host]["topics"]["status"], "offline", exit_on_error=False)
        mqtt_client.disconnect()

    # Use os._exit instead of sys.exit to ensure an MQTT disconnect event causes the program to exit correctly as they
    # occur on a separate thread
    os._exit(rc)

def refresh_storage_sensors():
    global hosts, devices, storage_poll_interval

    Timer(storage_poll_interval, refresh_storage_sensors).start()
    log(f"Fetching storage sensors for {len(hosts)} host(s)")

    for host in hosts:
        device = devices[host]
        topics = device["topics"]
        try:
            storage = device["camera"].storage_all

            mqtt_publish(topics["storage_used_percent"], str(storage["used_percent"]))
            mqtt_publish(topics["storage_used"], to_gb(storage["used"]))
            mqtt_publish(topics["storage_total"], to_gb(storage["total"]))
        except AmcrestError as error:
            log(f"Error fetching storage information for {host}: {error}", level="WARNING")

def to_gb(total):
    return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))

def signal_handler(sig, frame):
    # exit immediately upon receiving a second SIGINT
    global is_exiting

    if is_exiting:
        os._exit(1)

    is_exiting = True
    exit_gracefully(0)

def get_device(amcrest_host, amcrest_post, amcrest_username, amcrest_password, device_name):
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

    log(f"Vendor: {camera.vendor_information}")
    log(f"Device name: {device_name}")
    log(f"Device type: {device_type}")
    log(f"Serial number: {serial_number}")
    log(f"Software version: {amcrest_version}")
    log(f"Hardware version: {camera.hardware_version}")

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
      "topics": {
        "config": f"amcrest2mqtt/{serial_number}/config",
        "status": f"amcrest2mqtt/{serial_number}/status",
        "event": f"amcrest2mqtt/{serial_number}/event",
        "motion": f"amcrest2mqtt/{serial_number}/motion",
        "doorbell": f"amcrest2mqtt/{serial_number}/doorbell",
        "human": f"amcrest2mqtt/{serial_number}/human",
        "storage_used": f"amcrest2mqtt/{serial_number}/storage/used",
        "storage_used_percent": f"amcrest2mqtt/{serial_number}/storage/used_percent",
        "storage_total": f"amcrest2mqtt/{serial_number}/storage/total",
        "home_assistant_legacy": {
          "doorbell": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/{device_slug}_doorbell/config",
          "human": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/{device_slug}_human/config",
          "motion": f"{home_assistant_prefix}/binary_sensor/amcrest2mqtt-{serial_number}/{device_slug}_motion/config",
          "storage_used": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_storage_used/config",
          "storage_used_percent": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_storage_used_percent/config",
          "storage_total": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_storage_total/config",
          "version": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_version/config",
          "host": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_host/config",
          "serial_number": f"{home_assistant_prefix}/sensor/amcrest2mqtt-{serial_number}/{device_slug}_serial_number/config",
        },
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

def config_home_assistant(device):
    global mqtt_qos

    vendor = device["config"]["vendor"]
    device_name = device["config"]["device_name"]
    device_type = device["config"]["device_type"]
    device_slug = device["config"]["device_slug"]
    serial_number = device["config"]["serial_number"]
    amcrest_version = device["config"]["amcrest_version"]
    hw_version = device["config"]["hardware_version"]

    base_config = {
      "availability_topic": device["topics"]["status"],
      "qos": mqtt_qos,
      "device": {
        "name": f"{vendor} {device_type}",
        "manufacturer": vendor,
        "model": device_type,
        "identifiers": serial_number,
        "sw_version": amcrest_version,
        "hw_version": hw_version,
        "via_device": "amcrest2mqtt",
      },
    }

    if device["config"]["is_doorbell"]:
        doorbell_name = "Doorbell" if device_name == "Doorbell" else f"{device_name} Doorbell"

        mqtt_publish(device["topics"]["home_assistant_legacy"]["doorbell"], "")
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
        mqtt_publish(device["topics"]["home_assistant_legacy"]["human"], "")
        mqtt_publish(
          device["topics"]["home_assistant"]["human"],
          base_config
          | {
              "state_topic": device["topics"]["human"],
              "payload_on": "on",
              "payload_off": "off",
              "device_class": "motion",
              "name": f"{device_name} Human",
              "unique_id": f"{serial_number}.human",
          },
          json=True,
        )

    mqtt_publish(device["topics"]["home_assistant_legacy"]["motion"], "")
    mqtt_publish(
      device["topics"]["home_assistant"]["motion"],
      base_config
      | {
          "state_topic": device["topics"]["motion"],
          "payload_on": "on",
          "payload_off": "off",
          "device_class": "motion",
          "name": f"{device_name} Motion",
          "unique_id": f"{serial_number}.motion",
      },
      json=True,
    )

    mqtt_publish(device["topics"]["home_assistant_legacy"]["version"], "")
    mqtt_publish(
      device["topics"]["home_assistant"]["version"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.sw_version }}",
          "icon": "mdi:package-up",
          "name": f"{device_name} Version",
          "unique_id": f"{serial_number}.version",
          "entity_category": "diagnostic",
          "enabled_by_default": False
      },
      json=True,
    )

    mqtt_publish(device["topics"]["home_assistant_legacy"]["serial_number"], "")
    mqtt_publish(
      device["topics"]["home_assistant"]["serial_number"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.serial_number }}",
          "icon": "mdi:alphabetical-variant",
          "name": f"{device_name} Serial Number",
          "unique_id": f"{serial_number}.serial_number",
          "entity_category": "diagnostic",
          "enabled_by_default": False
      },
      json=True,
    )

    mqtt_publish(device["topics"]["home_assistant_legacy"]["host"], "")
    mqtt_publish(
      device["topics"]["home_assistant"]["host"],
      base_config
      | {
          "state_topic": device["topics"]["config"],
          "value_template": "{{ value_json.host }}",
          "icon": "mdi:ip-network",
          "name": f"{device_name} Host",
          "unique_id": f"{serial_number}.host",
          "entity_category": "diagnostic",
          "enabled_by_default": False
        },
        json=True,
    )

    if storage_poll_interval > 0:
        mqtt_publish(device["topics"]["home_assistant_legacy"]["storage_used_percent"], "")
        mqtt_publish(
          device["topics"]["home_assistant"]["storage_used_percent"],
          base_config
          | {
              "state_topic": device["topics"]["storage_used_percent"],
              "unit_of_measurement": "%",
              "icon": "mdi:micro-sd",
              "name": f"{device_name} Storage Used %",
              "object_id": f"{device_slug}_storage_used_percent",
              "unique_id": f"{serial_number}.storage_used_percent",
              "entity_category": "diagnostic",
          },
          json=True,
        )

        mqtt_publish(device["topics"]["home_assistant_legacy"]["storage_used"], "")
        mqtt_publish(
          device["topics"]["home_assistant"]["storage_used"],
          base_config
          | {
              "state_topic": device["topics"]["storage_used"],
              "unit_of_measurement": "GB",
              "icon": "mdi:micro-sd",
              "name": f"{device_name} Storage Used",
              "unique_id": f"{serial_number}.storage_used",
              "entity_category": "diagnostic",
          },
          json=True,
        )

        mqtt_publish(device["topics"]["home_assistant_legacy"]["storage_total"], "")
        mqtt_publish(
          device["topics"]["home_assistant"]["storage_total"],
          base_config
          | {
              "state_topic": device["topics"]["storage_total"],
              "unit_of_measurement": "GB",
              "icon": "mdi:micro-sd",
              "name": f"{device_name} Storage Total",
              "unique_id": f"{serial_number}.storage_total",
              "entity_category": "diagnostic",
          },
          json=True,
        )

def camera_online(device):
    mqtt_publish(device["topics"]["status"], "online")
    mqtt_publish(device["topics"]["config"], {
      "version": device["config"]["amcrest_version"],
      "device_type": device["config"]["device_type"],
      "device_name": device["config"]["device_name"],
      "sw_version": device["config"]["amcrest_version"],
      "hw_version": device["config"]["hardware_version"],
      "serial_number": device["config"]["serial_number"],
      "host": device["config"]["amcrest_host"],
    }, json=True)


# Exit if any of the required vars are not provided
if amcrest_hosts is None:
    log("Please set the AMCREST_HOSTS environment variable", level="ERROR")
    sys.exit(1)
hosts = amcrest_hosts.split()
host_count = len(hosts)

if device_names is None:
    log("Please set the DEVICE_NAMES environment variable", level="ERROR")
    sys.exit(1)
names = device_names.split()
name_count = len(names)

if host_count != name_count:
    log("The AMCREST_HOSTS and DEVICE_NAMES must have the same number of space-delimited hosts/names", level="ERROR")
    sys.exit(1)

if amcrest_password is None:
    log("Please set the AMCREST_PASSWORD environment variable", level="ERROR")
    sys.exit(1)

version = read_version()
log(f"App Version: {version}")

# Handle interruptions
signal.signal(signal.SIGINT, signal_handler)

# Connect to each camera, if not already
for host in hosts:
    name = names.pop(0)
    log(f"Connecting host: {host} as {name}", level="INFO")
    devices[host] = get_device(host, amcrest_port, amcrest_username, amcrest_password, name)
log(f"Connecting to hosts done.", level="INFO")

# connect to MQTT service
mqtt_connect()

# Configure Home Assistant
if home_assistant:
    for host in hosts:
        config_home_assistant(devices[host])

# Main loop
for host in hosts:
    camera_online(devices[host])

if storage_poll_interval > 0:
    refresh_storage_sensors()

log(f"Listening for events on {len(hosts)} host(s)", level="DEBUG")

async def main():
    try:
        for host in hosts:
            device = devices[host]
            config = device["config"]
            topics = device["topics"]
            async for code, payload in device["camera"].async_event_actions("All"):
                log(f"Event on {host}: {str(payload)}", level="DEBUG")
                if ((code == "ProfileAlarmTransmit" and config["is_ad110"])
                or (code == "VideoMotion" and not config["is_ad110"])):
                    motion_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(topics["motion"], motion_payload)
                elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                    human_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(topics["human"], human_payload)
                elif code == "_DoTalkAction_":
                    doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                    mqtt_publish(topics["doorbell"], doorbell_payload)

                mqtt_publish(topics["event"], payload, json=True)

    except AmcrestError as error:
        log(f"Amcrest error while working on {host}: {AmcrestError}", level="ERROR")
        time.sleep(10)

asyncio.run(main())
