#!/bin/bash

mosquitto_sub -h mosquitto.graystorm.com -v -t '#' --retained-only \
  | grep 'amcrest2mqtt' \
  | while read -r topic payload ; do
      mosquitto_pub -h mosquitto.graystorm.com -t "$topic" -n -r
      echo "Purged $topic"
    done
echo "done."
