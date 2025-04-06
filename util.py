# This software is licensed under the MIT License, which allows you to use,
# copy, modify, merge, publish, distribute, and sell copies of the software,
# with the requirement to include the original copyright notice and this
# permission notice in all copies or substantial portions of the software.
#
# The software is provided 'as is', without any warranty.

import ipaddress
import os
import socket

# Helper functions and callbacks
def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile('./VERSION'):
        return read_file('./VERSION')

    return read_file('../VERSION')

def to_gb(total):
    return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))

def is_ipv4(string):
        try:
            ipaddress.IPv4Network(string)
            return True
        except ValueError:
            return False

def get_ip_address(string):
    if is_ipv4(string):
        return string
    for i in socket.getaddrinfo(string, 0):
        if i[0] is socket.AddressFamily.AF_INET and i[1] is socket.SocketKind.SOCK_RAW:
            return i[4][0]
    raise Exception(f'failed to find ip address for {string}')