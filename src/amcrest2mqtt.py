from slugify import slugify
from amcrest import AmcrestCamera, AmcrestError
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import os
import sys
from json import dumps
import signal
from threading import Timer
import ssl
import asyncio

is_exiting = False
mqtt_client = None

config = {}
cameras = {}
camera_configs = {}
camera_topics = {}

# Read env variables
amcrest_hosts = os.getenv("AMCREST_HOSTS")
amcrest_port = int(os.getenv("AMCREST_PORT") or 80)
amcrest_username = os.getenv("AMCREST_USERNAME") or "admin"
amcrest_password = os.getenv("AMCREST_PASSWORD")

storage_poll_interval = int(os.getenv("STORAGE_POLL_INTERVAL") or 3600)
device_names = os.getenv("DEVICE_NAMES")

mqtt_host = os.getenv("MQTT_HOST") or "localhost"
config["mqtt_qos"] = int(os.getenv("MQTT_QOS") or 0)
mqtt_port = int(os.getenv("MQTT_PORT") or 1883)
mqtt_username = os.getenv("MQTT_USERNAME")
mqtt_password = os.getenv("MQTT_PASSWORD")  # can be None
mqtt_tls_enabled = os.getenv("MQTT_TLS_ENABLED") == "true"
mqtt_tls_ca_cert = os.getenv("MQTT_TLS_CA_CERT")
mqtt_tls_cert = os.getenv("MQTT_TLS_CERT")
mqtt_tls_key = os.getenv("MQTT_TLS_KEY")

home_assistant = os.getenv("HOME_ASSISTANT") == "true"
home_assistant_prefix = os.getenv("HOME_ASSISTANT_PREFIX") or "homeassistant"

def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile("./VERSION"):
        return read_file("./VERSION")

    return read_file("../VERSION")

# Helper functions and callbacks
def log(msg, level="INFO"):
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S")
    print(f"{ts} [{level}] {msg}")

def mqtt_publish(topic, payload, exit_on_error=True, json=False):
    global mqtt_client

    msg = mqtt_client.publish(
        topic, payload=(dumps(payload) if json else payload), qos=config["mqtt_qos"], retain=True
    )

    if msg.rc == mqtt.MQTT_ERR_SUCCESS:
        msg.wait_for_publish(2)
        return

    log(f"Error publishing MQTT message: {mqtt.error_string(msg.rc)}", level="ERROR")

    if exit_on_error:
        exit_gracefully(msg.rc, skip_mqtt=True)

def on_mqtt_disconnect(client, userdata, rc):
    if rc != 0:
        if rc == 5:
          log(f"MQTT connection not authorized", level="ERROR")
        else:
          log(f"Unexpected MQTT disconnection: {rc}", level="ERROR")
        exit_gracefully(rc, skip_mqtt=True)

def exit_gracefully(rc, skip_mqtt=False):
    global hosts, camera_topics, mqtt_client

    log("Exiting app...")

    if mqtt_client is not None and mqtt_client.is_connected() and skip_mqtt == False:
        for host in hosts:
          topics = camera_topics[host]
          mqtt_publish(topics["status"], "offline", exit_on_error=False)
        mqtt_client.disconnect()

    # Use os._exit instead of sys.exit to ensure an MQTT disconnect event causes the program to exit correctly as they
    # occur on a separate thread
    os._exit(rc)

def refresh_storage_sensors():
    global hosts, camera, camera_topics, storage_poll_interval

    Timer(storage_poll_interval, refresh_storage_sensors).start()
    log("Fetching storage sensors...")

    for host in hosts:
      topics = camera_topics[host]
      try:
        storage = cameras[host].storage_all

        mqtt_publish(topics["storage_used_percent"], str(storage["used_percent"]))
        mqtt_publish(topics["storage_used"], to_gb(storage["used"]))
        mqtt_publish(topics["storage_total"], to_gb(storage["total"]))
      except AmcrestError as error:
        log(f"Error fetching storage information {error}", level="WARNING")

def to_gb(total):
    return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))

def signal_handler(sig, frame):
    # exit immediately upon receiving a second SIGINT
    global is_exiting

    if is_exiting:
        os._exit(1)

    is_exiting = True
    exit_gracefully(0)

def get_camera(amcrest_host, amcrest_post, amcrest_username, amcrest_password, device_name):
  camera = AmcrestCamera(
      amcrest_host, amcrest_port, amcrest_username, amcrest_password
  ).camera

  # Fetch camera details
  log("Fetching camera details...")

  camera_config = {}
  camera_config["device_name"] = device_name
  camera_config["amcrest_host"] = amcrest_host
  try:
    camera_config["device_type"] = device_type = camera.device_type.replace("type=", "").strip()
    is_ad110 = camera_config["device_type"] == "AD110"
    camera_config["is_ad410"] = is_ad410 = camera_config["device_type"] == "AD410"
    camera_config["is_doorbell"] = is_doorbell = is_ad110 or is_ad410
    camera_config["serial_number"] = serial_number = camera.serial_number

    if not isinstance(serial_number, str):
        log(f"Error fetching serial number", level="ERROR")
        exit_gracefully(1)

    sw_version = camera.software_information[0].replace("version=", "").strip()
    build_version = camera.software_information[1].strip()

    config["amcrest_version"] = amcrest_version = f"{sw_version} ({build_version})"

    if not device_name:
        device_name = camera.machine_name.replace("name=", "").strip()

    camera_config["device_slug"] = device_slug = slugify(device_name, separator="_")
  except AmcrestError as error:
    log(f"Error fetching camera details", level="ERROR")
    exit_gracefully(1)

  log(f"Device type: {device_type}")
  log(f"Serial number: {serial_number}")
  log(f"Software version: {amcrest_version}")
  log(f"Device name: {device_name}")

  setup = {}
  setup["camera"] = camera
  setup["camera_config"] = camera_config
  setup["camera_topic"] = {
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
  }

  return setup

def config_home_assistant(config, camera_config, topics):
    amcrest_version = config["amcrest_version"]
    device_name = camera_config["device_name"]
    device_slug = camera_config["device_slug"]
    device_type = camera_config["device_type"]
    serial_number = camera_config["serial_number"]

    base_config = {
        "availability_topic": topics["status"],
        "qos": config["mqtt_qos"],
        "device": {
            "name": f"Amcrest {device_type}",
            "manufacturer": "Amcrest",
            "model": device_type,
            "identifiers": serial_number,
            "sw_version": amcrest_version,
            "via_device": "amcrest2mqtt",
        },
    }

    if camera_config["is_doorbell"]:
        doorbell_name = "Doorbell" if device_name == "Doorbell" else f"{device_name} Doorbell"

        mqtt_publish(topics["home_assistant_legacy"]["doorbell"], "")
        mqtt_publish(
            topics["home_assistant"]["doorbell"],
            base_config
            | {
                "state_topic": topics["doorbell"],
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:doorbell",
                "name": doorbell_name,
                "unique_id": f"{serial_number}.doorbell",
            },
            json=True,
        )

    if camera_config["is_ad410"]:
        mqtt_publish(topics["home_assistant_legacy"]["human"], "")
        mqtt_publish(
            topics["home_assistant"]["human"],
            base_config
            | {
                "state_topic": topics["human"],
                "payload_on": "on",
                "payload_off": "off",
                "device_class": "motion",
                "name": f"{device_name} Human",
                "unique_id": f"{serial_number}.human",
            },
            json=True,
        )

    mqtt_publish(topics["home_assistant_legacy"]["motion"], "")
    mqtt_publish(
        topics["home_assistant"]["motion"],
        base_config
        | {
            "state_topic": topics["motion"],
            "payload_on": "on",
            "payload_off": "off",
            "device_class": "motion",
            "name": f"{device_name} Motion",
            "unique_id": f"{serial_number}.motion",
        },
        json=True,
    )

    mqtt_publish(topics["home_assistant_legacy"]["version"], "")
    mqtt_publish(
        topics["home_assistant"]["version"],
        base_config
        | {
            "state_topic": topics["config"],
            "value_template": "{{ value_json.sw_version }}",
            "icon": "mdi:package-up",
            "name": f"{device_name} Version",
            "unique_id": f"{serial_number}.version",
            "entity_category": "diagnostic",
            "enabled_by_default": False
        },
        json=True,
    )

    mqtt_publish(topics["home_assistant_legacy"]["serial_number"], "")
    mqtt_publish(
        topics["home_assistant"]["serial_number"],
        base_config
        | {
            "state_topic": topics["config"],
            "value_template": "{{ value_json.serial_number }}",
            "icon": "mdi:alphabetical-variant",
            "name": f"{device_name} Serial Number",
            "unique_id": f"{serial_number}.serial_number",
            "entity_category": "diagnostic",
            "enabled_by_default": False
        },
        json=True,
    )

    mqtt_publish(topics["home_assistant_legacy"]["host"], "")
    mqtt_publish(
        topics["home_assistant"]["host"],
        base_config
        | {
            "state_topic": topics["config"],
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
        mqtt_publish(topics["home_assistant_legacy"]["storage_used_percent"], "")
        mqtt_publish(
            topics["home_assistant"]["storage_used_percent"],
            base_config
            | {
                "state_topic": topics["storage_used_percent"],
                "unit_of_measurement": "%",
                "icon": "mdi:micro-sd",
                "name": f"{device_name} Storage Used %",
                "object_id": f"{device_slug}_storage_used_percent",
                "unique_id": f"{serial_number}.storage_used_percent",
                "entity_category": "diagnostic",
            },
            json=True,
        )

        mqtt_publish(topics["home_assistant_legacy"]["storage_used"], "")
        mqtt_publish(
            topics["home_assistant"]["storage_used"],
            base_config
            | {
                "state_topic": topics["storage_used"],
                "unit_of_measurement": "GB",
                "icon": "mdi:micro-sd",
                "name": f"{device_name} Storage Used",
                "unique_id": f"{serial_number}.storage_used",
                "entity_category": "diagnostic",
            },
            json=True,
        )

        mqtt_publish(topics["home_assistant_legacy"]["storage_total"], "")
        mqtt_publish(
            topics["home_assistant"]["storage_total"],
            base_config
            | {
                "state_topic": topics["storage_total"],
                "unit_of_measurement": "GB",
                "icon": "mdi:micro-sd",
                "name": f"{device_name} Storage Total",
                "unique_id": f"{serial_number}.storage_total",
                "entity_category": "diagnostic",
            },
            json=True,
        )

def camera_online(config, camera_config, topics):
  amcrest_version = config["amcrest_version"]
  host = camera_config["amcrest_host"]
  device_name = camera_config["device_name"]
  device_slug = camera_config["device_slug"]
  device_type = camera_config["device_type"]
  serial_number = camera_config["serial_number"]

  mqtt_publish(topics["status"], "online")
  mqtt_publish(topics["config"], {
      "version": version,
      "device_type": device_type,
      "device_name": device_name,
      "sw_version": amcrest_version,
      "serial_number": serial_number,
      "host": host,
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
    log("The AMCREST_HOSTS and DEVICE_NAMES must have the same number of space-delimited devices", level="ERROR")
    sys.exit(1)

if amcrest_password is None:
    log("Please set the AMCREST_PASSWORD environment variable", level="ERROR")
    sys.exit(1)

if mqtt_username is None:
    log("Please set the MQTT_USERNAME environment variable", level="ERROR")
    sys.exit(1)

version = read_version()

log(f"App Version: {version}")

# Handle interruptions
signal.signal(signal.SIGINT, signal_handler)

# Connect to each camera, if not already 
for host in hosts:
  log(f"Working host: {host}", level="INFO")
  if host in cameras and camers[host].serial_number:
    continue
  setup = get_camera(host, amcrest_port, amcrest_username, amcrest_password, names.pop())
  cameras[host] = setup["camera"]
  camera_configs[host] = setup["camera_config"]
  camera_topics[host] = setup["camera_topic"]

# Connect to MQTT
mqtt_client = mqtt.Client(
    client_id=f"amcrest2mqtt_broker", clean_session=False
)
mqtt_client.on_disconnect = on_mqtt_disconnect
# send "will_set" for each connected camera
for host in hosts:
  if camera_topics[host]["status"]:
    mqtt_client.will_set(camera_topics[host]["status"], payload="offline", qos=config["mqtt_qos"], retain=True)

if mqtt_tls_enabled:
    log(f"Setting up MQTT for TLS")
    if mqtt_tls_ca_cert is None:
        log("Missing var: MQTT_TLS_CA_CERT", level="ERROR")
        sys.exit(1)
    if mqtt_tls_cert is None:
        log("Missing var: MQTT_TLS_CERT", level="ERROR")
        sys.exit(1)
    if mqtt_tls_cert is None:
        log("Missing var: MQTT_TLS_KEY", level="ERROR")
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
    mqtt_client.connect(mqtt_host, port=mqtt_port)
    mqtt_client.loop_start()
except ConnectionError as error:
    log(f"Could not connect to MQTT server: {error}", level="ERROR")
    sys.exit(1)

# Configure Home Assistant
if home_assistant:
    log("Writing Home Assistant discovery config...")

    for host in hosts:
      if host in camera_topics:
        config_home_assistant(config, camera_configs[host], camera_topics[host])

# Main loop
for host in hosts:
  if host in camera_topics:
    camera_online(config, camera_configs[host], camera_topics[host])

if storage_poll_interval > 0:
    refresh_storage_sensors()

log("Listening for events...")

async def main():
    try:
        for host in hosts:
            async for code, payload in cameras[host].async_event_actions("All"):
                if (camera_configs[host]["is_ad110"] and code == "ProfileAlarmTransmit") or (code == "VideoMotion" and not camera_configs[host]["is_ad110"]):
                    motion_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(camera_topics[host]["motion"], motion_payload)
                elif code == "CrossRegionDetection" and payload["data"]["ObjectType"] == "Human":
                    human_payload = "on" if payload["action"] == "Start" else "off"
                    mqtt_publish(camera_topics[host]["human"], human_payload)
                elif code == "_DoTalkAction_":
                    doorbell_payload = "on" if payload["data"]["Action"] == "Invite" else "off"
                    mqtt_publish(camera_topics[host]["doorbell"], doorbell_payload)

                mqtt_publish(camera_topics[host]["event"], payload, json=True)
                log(str(payload))

    except AmcrestError as error:
        log(f"Amcrest error: {AmcrestError}", level="ERROR")
        time.sleep(10)

asyncio.run(main())
