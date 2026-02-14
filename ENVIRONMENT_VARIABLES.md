# Environment Variables

While using a config.yaml file is the recommended approach, amcrest2mqtt also supports configuration via environment variables.

## Amcrest Camera Settings

-   `AMCREST_HOSTS` (required, 1+ space-separated list of hostnames/ips)
-   `AMCREST_NAMES` (required, 1+ space-separated list of device names - must match count of AMCREST_HOSTS)
-   `AMCREST_PORT` (optional, default = 80)
-   `AMCREST_USERNAME` (optional, default = admin)
-   `AMCREST_PASSWORD` (required)

## WebRTC Settings

-   `AMCREST_WEBRTC_HOST` (optional, webrtc hostname for link, but then link/sources below become required:)
-   `AMCREST_WEBRTC_PORT` (webrtc port, default = 1984)
-   `AMCREST_WEBRTC_LINK` (webrtc stream link, default = 'stream.html')
-   `AMCREST_WEBRTC_SOURCES` (webrtc "Source" param for each camera, same count and order of AMCREST_HOSTS above)

## MQTT Settings

-   `MQTT_USERNAME` (required)
-   `MQTT_PASSWORD` (optional, default = empty password)
-   `MQTT_HOST` (optional, default = 'localhost')
-   `MQTT_QOS` (optional, default = 0)
-   `MQTT_PORT` (optional, default = 1883)
-   `MQTT_PROTOCOL` (optional, default = '5') - MQTT protocol version: '3.1.1' or '5'
-   `MQTT_TLS_ENABLED` (required if using TLS) - set to `true` to enable
-   `MQTT_TLS_CA_CERT` (required if using TLS) - path to the ca certs
-   `MQTT_TLS_CERT` (required if using TLS) - path to the private cert
-   `MQTT_TLS_KEY` (required if using TLS) - path to the private key
-   `MQTT_PREFIX` (optional, default = amcrest2mqtt)
-   `MQTT_DISCOVERY_PREFIX` (optional, default = 'homeassistant')

## Media/Recording Settings

-   `MEDIA_PATH` (optional) - path to store motion recordings (mp4) files
-   `MEDIA_MAX_SIZE` (optional, default = 25) - max size per recording in MB
-   `MEDIA_RETENTION_DAYS` (optional, default = 7) - days to keep recordings, 0 = disabled
-   `MEDIA_SOURCE` (optional) - HomeAssistant url for accessing those recordings (see config.yaml.sample)

## Vision Settings

-   `VISION_REQUEST` (optional, default = false) - publish vision request on motion events for use with [vision2mqtt](https://github.com/weirdtangent/vision2mqtt)

## Update Intervals

-   `STORAGE_UPDATE_INTERVAL` (optional, default = 900) - how often to fetch storage stats (in seconds)
-   `SNAPSHOT_UPDATE_INTERVAL` (optional, default = 60) - how often to fetch camera snapshot (in seconds)
