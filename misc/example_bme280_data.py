#!/usr/bin/env python3

# Example of an external temperature script for indi-allsky
# STDOUT and STDERR are ignored
#
# The json output file is set in the environment variable TEMP_JSON

import os
import sys
import io
import json
import logging

import smbus2
import bme280

port = 3
address = 0x76
bus = smbus2.SMBus(port)

logging.basicConfig(level=logging.INFO)
logger = logging

calibration_params = bme280.load_calibration_params(bus, address)

# the sample method will take a single reading and return a
# compensated_reading object
data = bme280.sample(bus, address, calibration_params)

temp = data.temperature
press = data.pressure
humi = data.humidity

try:
    # data file is communicated via environment variable
    env_json = os.environ['ENV_JSON']
except KeyError:
    logger.error('ENV_JSON environment variable is not defined')
    sys.exit(1)

# dict to be used for json data
env_data = {
    'temp' : temp,
    'press' : press,
    'humi' : humi,
}

# write json data
with io.open(env_json, 'w') as f_env_json:
    json.dump(env_data, f_env_json, indent=4)

# script must exist with exit code 0 for success
sys.exit(0)

