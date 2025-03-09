# weirdtangent/amcrest2mqtt

Expose multiple Amcrest cameras and events to an MQTT broker, primarily
designed to work with Home Assistant. A WIP, since I'm new to Python.
Uses the [`python-amcrest`](https://github.com/tchellomello/python-amcrest) library.

Forked from [dchesterton/amcrest2mqtt](https://github.com/dchesterton/amcrest2mqtt)

You can define config in config.yaml and pass `-c path/to/config.yaml`. See the
`config.yaml.sample` file for an example.

Or, we support the following environment variables and defaults (though, this is becoming unwieldy):

-   `AMCREST_HOSTS` (required, 1+ space-separated list of hostnames/ips)
-   `AMCREST_NAMES` (required, 1+ space-separated list of device names - must match count of AMCREST_HOSTS)
-   `AMCREST_PORT` (optional, default = 80)
-   `AMCREST_USERNAME` (optional, default = admin)
-   `AMCREST_PASSWORD` (required)

-   `AMCREST_WEBRTC_HOST` (optional, webrtc hostname for link, but then link/sources below become required:)
-   `AMCREST_WEBRTC_PORT` (webrtc port, default = 1984)
-   `AMCREST_WEBRTC_LINK` (webrtc stream link, default = 'stream.html')
-   `AMCREST_WEBRTC_SOURCES` (webrtc "Source" param for each camera, same count and order of AMCREST_HOSTS above)

-   `MQTT_USERNAME` (required)
-   `MQTT_PASSWORD` (optional, default = empty password)
-   `MQTT_HOST` (optional, default = 'localhost')
-   `MQTT_QOS` (optional, default = 0)
-   `MQTT_PORT` (optional, default = 1883)
-   `MQTT_TLS_ENABLED` (required if using TLS) - set to `true` to enable
-   `MQTT_TLS_CA_CERT` (required if using TLS) - path to the ca certs
-   `MQTT_TLS_CERT` (required if using TLS) - path to the private cert
-   `MQTT_TLS_KEY` (required if using TLS) - path to the private key
-   `MQTT_PREFIX` (optional, default = amgrest2mqtt)
-   `MQTT_HOMEASSISTANT` (optional, default = true)
-   `MQTT_DISCOVERY_PREFIX` (optional, default = 'homeassistant')

-   `TZ` (required, timezone identifier, see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List)
-   `STORAGE_UPDATE_INTERVAL` (optional, default = 900) - how often to fetch storage stats (in seconds)
-   `SNAPSHOT_UPDATE_INTERVAL` (optional, default = 60) - how often to fetch camera snapshot (in seconds)

It exposes through device discovery a `service` and a `device` with components for each camera:

-   `homeassistant/device/amcrest-service` - service config

-   `homeassistant/device/amcrest-[SERIAL_NUMBER]` per camera, with components:
-    `event`    - all events
-    `camera`   - a snapshot is saved every SNAPSHOT_UPDATE_INTERVAL (also based on how often camera saves snapshot image)
-    `doorbell` - doorbell status (if AD110 or AD410)
-    `human`    - human detection (if AD410)
-    `motion`   - motion events (if supported)
-    `config`   - device configuration information
-    `storage`  - storage stats

## Snapshots, Area Cards, and WebRTC

The `camera` snapshots work really well for the HomeAssistant `Area` cards on a dashboard - just make this MQTT camera device the only camera for an area and place an `Area` card for that location. The WebRTC option works very well with the <a href="https://github.com/AlexxIT/go2rtc">go2rtc</a> package which is a streaming server that works very well for (my) Amcrest cameras. If you setup the WebRTC config here, the `configuration_url` for the MQTT device will be the streaming RTC link instead of just a link to the hostname (which is arguably more correctly a "configuration" url, but I'd rather have a simple link from the device page to a live stream)

## Device Support

The app supports events for any Amcrest device supported by [`python-amcrest`](https://github.com/tchellomello/python-amcrest).

## Home Assistant

The app has built-in support for Home Assistant discovery. Set the `MQTT_HOMEASSISTANT` environment variable to `true` to enable support.
If you are using a different MQTT prefix to the default, you will need to set the `MQTT_DISCOVERY_PREFIX` environment variable.

## Running the app

To run via env variables with Docker Compose, see docker-compose.yaml
or make sure you attach a volume with the config file and point to that directory, for example:
```
CMD [ "python", "-u", "./app.py", "-c", "/config" ]
```

## Out of Scope

### Non-Docker Environments

Docker is the only supported way of deploying the application. The app should run directly via Python but this is not supported.

## Buy Me A Coffee

A few people have kindly requested a way to donate a small amount of money. If you feel so inclined I've set up a "Buy Me A Coffee"
page where you can donate a small sum. Please do not feel obligated to donate in any way - I work on the app because it's
useful to myself and others, not for any financial gain - but any token of appreciation is much appreciated 🙂

<a href="https://buymeacoffee.com/weirdtangent">Buy Me A Coffee</a>

### How Happy am I?

<img src="https://github.com/weirdtangent/amcrest2mqtt/actions/workflows/deploy.yaml/badge.svg" />
