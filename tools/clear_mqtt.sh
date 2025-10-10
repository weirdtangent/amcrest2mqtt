#!/bin/sh

((gtimeout 1 mosquitto_sub -h mosquitto -t '#' -v) | grep -E '^(amcrest2mqtt/|homeassistant/[^/]+/amcrest2mqtt_)' | awk '{print $1}' | xargs -I TOPIC mosquitto_pub -h mosquitto -t TOPIC -r -n) 2>/dev/null
