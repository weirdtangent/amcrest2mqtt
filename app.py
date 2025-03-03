import asyncio
import argparse
from amcrest_mqtt import AmcrestMqtt
import os
import sys
import time
from util import *
import yaml

# Helper functions and callbacks
def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile('./VERSION'):
        return read_file('./VERSION')

    return read_file('../VERSION')

# Let's go!
version = read_version()
app_log(f'Starting: amcrest2mqtt v{version}')

# cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    '-c',
    '--config',
    required=False,
    help='Directory holding config.yaml or full path to config file',
)
args = argparser.parse_args()

# load config file
configpath = args.config or '/config'
try:
    if not configpath.endswith('.yaml'):
        if not configpath.endswith('/'):
            configpath += '/'
        configfile = configpath + 'config.yaml'
    with open(configfile) as file:
        config = yaml.safe_load(file)
    app_log(f'Reading config file {configpath}')
    config['config_from'] = 'file'
    config['config_path'] = configpath
except:
    app_log(f'config.yaml not found, checking ENV')
    config = {
        'mqtt': {
            'host': os.getenv('MQTT_HOST') or 'localhost',
            'qos': int(os.getenv('MQTT_QOS') or 0),
            'port': int(os.getenv('MQTT_PORT') or 1883),
            'username': os.getenv('MQTT_USERNAME'),
            'password': os.getenv('MQTT_PASSWORD'),  # can be None
            'tls_enabled': os.getenv('MQTT_TLS_ENABLED') == 'true',
            'tls_ca_cert': os.getenv('MQTT_TLS_CA_CERT'),
            'tls_cert': os.getenv('MQTT_TLS_CERT'),
            'tls_key': os.getenv('MQTT_TLS_KEY'),
            'prefix': os.getenv('MQTT_PREFIX') or 'amcrest2mqtt',
            'homeassistant': os.getenv('MQTT_HOMEASSISTANT') == True,
            'discovery_prefix': os.getenv('MQTT_DISCOVERY_PREFIX') or 'homeassistant',
        },
        'amcrest': {
            'hosts': os.getenv("AMCREST_HOSTS"),
            'names': os.getenv("AMCREST_NAMES"),
            'port': int(os.getenv("AMCREST_PORT") or 80),
            'username': os.getenv("AMCREST_USERNAME") or "admin",
            'password': os.getenv("AMCREST_PASSWORD"),
            'device_update_interval': int(os.getenv("DEVICE_UPDATE_INTERVAL") or 600),
        },
        'debug': True if os.getenv('DEBUG') else False,
        'hide_ts': True if os.getenv('HIDE_TS') else False,
        'config_from': 'env',
        'timezone': os.getenv('TZ'),
    }

config['version'] = version
config['configpath'] = os.path.dirname(configpath)
if not 'hide_ts' in config:
    config['hide_ts'] = False

# Exit if any of the required vars are not provided
if config['amcrest']['hosts'] is None:
    app_log("Missing env var: AMCREST_HOSTS or amcrest.hosts in config", level="ERROR")
    sys.exit(1)
config['amcrest']['host_count'] = len(config['amcrest']['hosts'])

if config['amcrest']['names'] is None:
    app_log("Missing env var: AMCREST_NAMES or amcrest.names in config", level="ERROR")
    sys.exit(1)
config['amcrest']['name_count'] = len(config['amcrest']['names'])

if config['amcrest']['host_count'] != config['amcrest']['name_count']:
    app_log("The AMCREST_HOSTS and AMCREST_NAMES must have the same number of space-delimited hosts/names", level="ERROR")
    sys.exit(1)
app_log(f"Found {config['amcrest']['host_count']} host(s) defined to monitor")

if config['amcrest']['password'] is None:
    app_log("Please set the AMCREST_PASSWORD environment variable", level="ERROR")
    sys.exit(1)

if not 'timezone' in config:
    app_log('`timezone` required in config file or in TZ env var', level='ERROR', tz=timezone)
    exit(1)
else:
    app_log(f'TIMEZONE set as {config["timezone"]}', tz=config["timezone"])

try:
    with AmcrestMqtt(config) as mqtt:
        asyncio.run(mqtt.main_loop())
except Exception as err:
    app_log(f'CAUGHT IN app: {err}', level='ERROR')