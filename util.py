import os

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
