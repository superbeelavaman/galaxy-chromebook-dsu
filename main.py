import os
import struct
import socket
from binascii import crc32
import time
import threading

dataTypes = dict(version=bytes([0x00, 0x00, 0x10, 0x00]),
				ports=bytes([0x01, 0x00, 0x10, 0x00]),
				data=bytes([0x02, 0x00, 0x10, 0x00]))


iioDevices = []
iioPath = "/sys/bus/iio/devices/iio:device"

def getIIODevices(): # Get list of IIO devices (Gyroscope, Accelerometers, Light Sensors, Lid Angle)
	for i in range(0, 6):
		device = os.popen(f'cat {iioPath}{i}/name {iioPath}{i}/label | tr "\\n" " "').read()
		iioDevices.append(device [0:-1])

def readSensorValue(file):
	file.seek(0)
	value=file.read()
	if value=='':
		return 0
	return int(value)

def checkSensors(): # Read sensor values and save to global variables
	global baseGyroXMotion # todo: make it look better, store sensors in a dictionary
	global baseGyroYMotion
	global baseGyroZMotion
	global baseAccelXMotion
	global baseAccelYMotion
	global baseAccelZMotion
	global screenAccelXMotion
	global screenAccelYMotion
	global screenAccelZMotion
	global in_angl
	global in_illuminance_base
	global in_illuminance_display
	global batteryCap
	global batteryChrg
	in_angl=readSensorValue(angl)
	in_illuminance_base=readSensorValue(baseLight)
	in_illuminance_display=readSensorValue(screenLight)
	baseGyroXMotion = readSensorValue(baseGyroX)
	baseGyroYMotion = readSensorValue(baseGyroY)
	baseGyroZMotion = readSensorValue(baseGyroZ)
	baseAccelXMotion = readSensorValue(baseAccelX)
	baseAccelYMotion = readSensorValue(baseAccelY)
	baseAccelZMotion = readSensorValue(baseAccelZ)
	screenAccelXMotion = readSensorValue(screenAccelX)
	screenAccelYMotion = readSensorValue(screenAccelY)
	screenAccelZMotion = readSensorValue(screenAccelZ)
	batteryCap = readSensorValue(batteryCapacity)
	batteryStatus.seek(0)
	batteryChrg = (str(batteryStatus.read()) == "Charging\n")

def finalizeMessage(messageType, data): # Attaches header and calculates CRC
	message=[
		0x44, 0x53, 0x55, 0x53, # DSUS
		0xE9, 0x03, # protocol version 1001
		*struct.pack('<H', len(data) + 4), # data length
		0x00, 0x00, 0x00, 0x00, # space for CRC32
		0xAA, 0xBB, 0xCC, 0xDD, # server ID
		*dataTypes[messageType], # data type
		*data
	]
	crc = crc32(bytes(message)) & 0xffffffff
	message[8:12] = struct.pack('<I', crc)
	return bytes(message)

def readMessage(message): # read received message and decode request
	if message[0:4] == 'DSUC'.encode():
		if int.from_bytes(message[4:6], "little") != 1001:
			print("Warning: Wrong DSU protocol version or malformed request!")
			return 0
		packetSize = int.from_bytes(message[6:8], "little") - 4
		readCRC = message[8:12]
		serverID = message[12:16]
		packetTypeBin = message[16:20]
		packetType = list(dataTypes.keys())[list(dataTypes.values()).index(packetTypeBin)]
		if packetType == "ports":
			numPorts = int.from_bytes(message[20:24], "little")
			ports = []
			for x in range(0,numPorts):
				ports.append(message[24+x])
			return ('ports', numPorts, ports, None)
		elif packetType == "data":
			action = message[20:21]
			slot = message[21:22]
			mac = message[22:28]
			return ('data', action, slot, mac)
		elif packetType == "protocol":
			return ('protocol', None, None, None)


		
	else:
		print("Warning: Client is not a DSU Client! (got " + str(message[0:4])[2:6] + " instead of DSUC)\nCheck your settings in other apps!")
		return 0


def getBatteryStatusByte(percent, charging): # Convert battery status to byte value used by DSU
	if percent == None:
		return 0x00
	elif charging:
		if percent < 90:
			return 0xEE
		else:
			return 0xEF
	else:
		if percent < 10:
			return 0x01
		elif percent < 25:
			return 0x02
		elif percent < 75:
			return 0x03
		elif percent < 90:
			return 0x04
		else:
			return 0x05

def generateControllerHeader(slot, batteryPercent, batteryCharging): # Generate header for controller-related packets
	if slot == 0:
		model = 0x02
	elif slot == 1:
		model = 0x01
	else:
		model = 0x00
	controllerHeader=[
		slot, # slot number
		0x02,  # connection state
		model,  # device model
		0x00,  # connection method
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, # mac address
		getBatteryStatusByte(batteryPercent, batteryCharging)
	]
	return controllerHeader	

def generateControllerData(slot, packetNum): # Generate data packet for controller read
	if slot == 0:
		connected = 0x01
		if in_angl <= 360:
			leftX = int((in_angl/360)*255) & 0xFF
			tabletMode = 0x00
		else:
			leftX = 0xFF
			tabletMode = 0x01
		light = in_illuminance_base
		touchEnabled = 0x01
		accelTimeStamp = int(time.monotonic()*(10**6))
		motion = [
			*struct.pack('<Q', accelTimeStamp),
			*struct.pack('<f', -baseAccelXMotion/65536),
			*struct.pack('<f', -baseAccelZMotion/65536),
			*struct.pack('<f', baseAccelYMotion/65536),
			*struct.pack('<f', baseGyroXMotion/32),
			*struct.pack('<f', -baseGyroZMotion/32),
			*struct.pack('<f', baseGyroYMotion/32),
		]
	elif slot == 1:
		connected = 0x01
		leftX = 0x00
		tabletMode = 0x00
		light = in_illuminance_display
		touchEnabled = 0x01
		accelTimeStamp = int(time.monotonic()*(10**6))
		motion = [
			*struct.pack('<Q', accelTimeStamp),
			*struct.pack('<f', -screenAccelXMotion/65536),
			*struct.pack('<f', -screenAccelYMotion/65536),
			*struct.pack('<f', -screenAccelZMotion/65536),
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
		]
	else:
		connected = 0x00
		light = 0x00
		tabletMode = 0x00
		leftX = 0x00
		touchEnabled = 0x00
		motion = [
			0x00, 0x00, 0x00, 0x00,0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
			0x00, 0x00, 0x00, 0x00,
		]
	data = [
		connected,
		*struct.pack('<I', packetNum & 0xFFFFFFFF),
		0x00,
		0x00,
		tabletMode,
		0x00,
		leftX,  # LX
		0x00,   # LY
		0x00,   # RX
		0x00,   # RY
		0x00,   # A Dpad W
		0x00,   # A Dpad S
		0x00,   # A Dpad E
		0x00,   # A Dpad N
		0x00,   # Button W
		0x00,   # Button S
		0x00,   # Button E
		0x00,   # Button N
		0x00,   # R1
		0x00,   # L1
		0x00,   # R2
		0x00,   # L2
		#--Touch 1--#
		touchEnabled,
		touchEnabled,
		*struct.pack('<H', light & 0x1FFF),
		0x00, 0x00,
		#--Touch 2--#
		0x00,
		0x00,
		0x00, 0x00,
		0x00, 0x00,
		#--Accelerometer and Gyro--#
		*motion
	]
	return data

def scream(): # repeatedly send "controller" data to emulator
	global screamBusy
	while stillScreaming:
		screamBusy = True
		while pauseScream:
			pass
		for controller in screaming.keys():
			if screaming[controller] + 2 <= int(time.monotonic()):
				print("old controller deleted")
				del screaming[controller]
				break
			else:
				controllerID, address = controller
				sendControllerData(controllerID, address)
		screamBusy = False
		time.sleep(0.1)

def sendControllerData(controllerID, address): # assemble controller data packet from header and data and send to emulator
	checkSensors()
	global packetNum
	packetNum += 1
	controllerData = [
		*generateControllerHeader(int.from_bytes(controllerID), batteryCap, batteryChrg),
		*generateControllerData(int.from_bytes(controllerID), packetNum),
	]
	response = finalizeMessage(messageType, controllerData)
	serverSocket.sendto(response, address)

# Prepare most variables
getIIODevices()
anglID = iioDevices.index("cros-ec-lid-angle")
angl = open(f'{iioPath}{anglID}/in_angl_raw', 'r')
baseGyroID = iioDevices.index("cros-ec-gyro accel-base")
baseAccelID = iioDevices.index("cros-ec-accel accel-base")
screenAccelID = iioDevices.index("cros-ec-accel accel-display")
screenLightID = iioDevices.index("cros-ec-light accel-display")
baseLightID = iioDevices.index("cros-ec-light accel-base")
baseGyroX = open(f'{iioPath}{baseGyroID}/in_anglvel_x_raw', 'r')
baseGyroXMotion = 0
baseGyroY = open(f'{iioPath}{baseGyroID}/in_anglvel_y_raw', 'r')
baseGyroYMotion = 0
baseGyroZ = open(f'{iioPath}{baseGyroID}/in_anglvel_z_raw', 'r')
baseGyroZMotion = 0
baseAccelX = open(f'{iioPath}{baseAccelID}/in_accel_x_raw', 'r')
baseAccelY = open(f'{iioPath}{baseAccelID}/in_accel_y_raw', 'r')
baseAccelZ = open(f'{iioPath}{baseAccelID}/in_accel_z_raw', 'r')
screenAccelX = open(f'{iioPath}{screenAccelID}/in_accel_x_raw', 'r')
screenAccelY = open(f'{iioPath}{screenAccelID}/in_accel_y_raw', 'r')
screenAccelZ = open(f'{iioPath}{screenAccelID}/in_accel_z_raw', 'r')
screenLight = open(f'{iioPath}{screenLightID}/in_illuminance_input', 'r')
baseLight = open(f'{iioPath}{baseLightID}/in_illuminance_input', 'r')
batteryCapacity = open('/sys/class/power_supply/BAT0/capacity', 'r')
batteryStatus = open('/sys/class/power_supply/BAT0/status', 'r')
in_angl = 0
in_illuminance_base = 0
in_illuminance_display = 0
batteryCap = 0
batteryChrg = 0
packetNum = 0

serverSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
serverSocket.bind(('',26760))

# prepare and start secondary thread to scream controller data at emulator
screaming = {}
stillScreaming = True
screams = threading.Thread(target=scream)
screamBusy = False
pauseScream = False
screams.start()

# main loop (waiting for message from emulator)
try:
	while True:
		message, address = serverSocket.recvfrom(1024)
		messageType, dat1, dat2, dat3 = readMessage(message)
		checkSensors()
		if messageType == 'ports':
			for slot in dat2:
				data = [
					*generateControllerHeader(slot, batteryCap, batteryChrg),
					0x00
				]
				response = finalizeMessage(messageType, data)
				serverSocket.sendto(response, address)
		if messageType == 'data':
			while screamBusy:
				pass
			pauseScream = True
			if int.from_bytes(dat1) <= 1:
				if int.from_bytes(dat2) <= 1:
					screaming[(dat2, address)] = int(time.monotonic())
					sendControllerData(dat2, address)
			pauseScream = False
		if messageType == 'protocol':
			data = [
				0xE9, 0x03,
			]
			response = finalizeMessage(messageType, data)
			serverSocket.sendto(response, address)
except KeyboardInterrupt:
	stillScreaming = False
