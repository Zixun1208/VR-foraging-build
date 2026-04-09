import nidaqmx
from nidaqmx.system import System

# Get the local system
system = System.local()

# List device names
print("Devices found:")
for device in system.devices:
    print(device.name)
