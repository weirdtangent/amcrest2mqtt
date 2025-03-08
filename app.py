import asyncio
import argparse
from amcrest_mqtt import AmcrestMqtt
import logging
import os
import sys
import time
from util import *
import yaml

# Let's go!
version = read_version()

# Cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    '-c',
    '--config',
    required=False,
    help='Directory holding config.yaml or full path to config file',
)
args = argparser.parse_args()

# Setup config from yaml file or env
configpath = args.config or '/config'
try:
    if not configpath.endswith('.yaml'):
        if not configpath.endswith('/'):
            configpath += '/'
        configfile = configpath + 'config.yaml'
    with open(configfile) as file:
        config = yaml.safe_load(file)
    config['config_path'] = configpath
    config['config_from'] = 'file'
except:
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
            'storage_update_interval': int(os.getenv("STORAGE_UPDATE_INTERVAL") or 900),
            'snapshot_update_interval': int(os.getenv("SNAPSHOT_UPDATE_INTERVAL") or 300),
            'webrtc': {
                'host': os.getenv("AMCREST_WEBRTC_HOST"),
                'port': int(os.getenv("AMCREST_WEBRTC_PORT") or 1984),
                'link': os.getenv("AMCREST_WEBRTC_LINK") or 'stream.html',
                'sources': os.getenv("AMCREST_WEBRTC_SOURCES"),
            },
        },
        'debug': True if os.getenv('DEBUG') else False,
        'hide_ts': True if os.getenv('HIDE_TS') else False,
        'timezone': os.getenv('TZ'),
        'config_from': 'env',
    }
config['version'] = version
config['configpath'] = os.path.dirname(configpath)
if 'username' not in config['mqtt']: config['mqtt']['username'] = ''
if 'password' not in config['mqtt']: config['mqtt']['password'] = ''
if 'qos' not in config['mqtt']: config['mqtt']['qos'] = 0
if 'timezone' not in config: config['timezone'] = 'UTC'
if 'debug' not in config: config['debug'] = os.getenv('DEBUG') or False

logging.basicConfig(
    format = '%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s' if config['hide_ts'] == False else '[%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info(f'Starting: amcrest2mqtt v{version}')
logger.info(f'Config loaded from {config["config_from"]}')

# Check for required config properties
if config['amcrest']['hosts'] is None:
    logger.error('Missing env var: AMCREST_HOSTS or amcrest.hosts in config')
    exit(1)
config['amcrest']['host_count'] = len(config['amcrest']['hosts'])

if config['amcrest']['names'] is None:
    logger.error('Missing env var: AMCREST_NAMES or amcrest.names in config')
    exit(1)
config['amcrest']['name_count'] = len(config['amcrest']['names'])

if config['amcrest']['host_count'] != config['amcrest']['name_count']:
    logger.error('The AMCREST_HOSTS and AMCREST_NAMES must have the same number of space-delimited hosts/names')
    exit(1)
logger.info(f'Found {config["amcrest"]["host_count"]} host(s) defined to monitor')

if 'webrtc' in config['amcrest']:
    webrtc = config['amcrest']['webrtc']
    if 'host' not in webrtc:
        logger.error('Missing HOST in webrtc config')
        exit(1)
    if 'sources' not in webrtc:
        logger.error('Missing SOURCES in webrtc config')
        exit(1)
    config['amcrest']['webrtc_sources_count'] = len(config['amcrest']['webrtc']['sources'])
    if config['amcrest']['host_count'] != config['amcrest']['webrtc_sources_count']:
        logger.error('The AMCREST_HOSTS and AMCREST_WEBRTC_SOURCES must have the same number of space-delimited hosts/names')
        exit(1)
    if 'port' not in webrtc: webrtc['port'] = 1984
    if 'link' not in webrtc: webrtc['link'] = 'stream.html'

if config['amcrest']['password'] is None:
    logger.error('Please set the AMCREST_PASSWORD environment variable')
    exit(1)

# Go!
with AmcrestMqtt(config) as mqtt:
    asyncio.run(mqtt.main_loop())