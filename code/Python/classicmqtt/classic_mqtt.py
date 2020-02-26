#!/usr/bin/env python

from pymodbus.client.sync import ModbusTcpClient as ModbusClient
from paho.mqtt import client as mqttclient
from collections import OrderedDict
import json
import time
import threading

from classic_modbusdecoder import getRegisters, getDataDecoder, doDecode
from classic_jsonencoder import encodeClassicData_readings, encodeClassicData_info

MODBUS_POLL_RATE = 5                #Get data from the Classic every 5 seconds
MQTT_PUBLISH_RATE = 5               #Check to see if anything needs publishing every 5 seconds.
MQTT_SNOOZE_COUNT = 60              #When no one is listening, publish every 5 minutes
WAKE_COUNT = 60                     #The number of times to publish after getting a "wake"
MQTT_ROOT_DEFAULT = "ClassicMQTT"

mqttRoot = MQTT_ROOT_DEFAULT
classicModbusData = dict()
snoozeCount = 0
snoozing = True
wakeCount = 0
infoPublished = True

doStop = False



# --------------------------------------------------------------------------- # 
# configure the client logging
# --------------------------------------------------------------------------- # 

import logging
FORMAT = ('%(asctime)-15s %(threadName)-15s'
          ' %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s')
logging.basicConfig(format=FORMAT)
log = logging.getLogger()
log.setLevel(logging.INFO)

# --------------------------------------------------------------------------- # 
# Run the main payload decoder
# --------------------------------------------------------------------------- # 
def getModbusData():
    # ----------------------------------------------------------------------- #
    # We are going to use a simple client to send our requests
    # ----------------------------------------------------------------------- #
    modclient = ModbusClient('0.tcp.ngrok.io', port=15284)
    modclient.connect()

    theData = dict()

    #Read in all the registers at one time
    theData[4100] = getRegisters(theClient=modclient,addr=4100,count=44)
    theData[4360] = getRegisters(theClient=modclient,addr=4360,count=22)
    theData[4163] = getRegisters(theClient=modclient,addr=4163,count=2)
    theData[4209] = getRegisters(theClient=modclient,addr=4209,count=4)
    theData[4243] = getRegisters(theClient=modclient,addr=4243,count=32)
    #theData[16384]= getRegisters(theClient=modclient,addr=16384,count=12)

    # ----------------------------------------------------------------------- #
    # close the client
    # ----------------------------------------------------------------------- #
    modclient.close()

    #Iterate over them and get the decoded data all into one dict
    decoded = dict()
    for index in theData:
        decoded = {**dict(decoded), **dict(doDecode(index, getDataDecoder(theData[index])))}

    return decoded

def on_connect(client, userdata, flags, rc):
    if rc==0:
        print("MQTT connected OK Returned code=",rc)
    else:
        print("MQTT Bad connection Returned code=",rc)


def on_message(client, userdata, message):
        #print("Received message '" + str(message.payload) + "' on topic '"
        #+ message.topic + "' with QoS " + str(message.qos))

        global wakeCount
        global infoPublished
        global snoozing
        global doStop

        print(message.payload)
        msg = message.payload.decode(encoding='UTF-8')
        msg = msg.upper()

        print(msg)

        if msg == "{\"WAKE\"}":
            wakeCount = 0
            infoPublished = False
            snoozing = False
        elif msg == "{\"INFO\"}":
            wakeCount = 0
            infoPublished = False
            snoozing = False
        elif msg == "STOP":
            doStop = True
        else:
            print("Received something else")
            

# --------------------------------------------------------------------------- # 
# Read from the address and return a decoder
# --------------------------------------------------------------------------- # 
def mqttPublish(client, data, subtopic):
    global mqttRoot

    topic = "{}/classic/stat/{}".format(mqttRoot, subtopic)
    print(topic)
    client.publish(topic,data)


def publish(client):
    global infoPublished, classicModbusData

    #print(encodeClassicData_info(classicModbusData))
    if (not infoPublished):
        #Check if the Info has been published yet
        mqttPublish(client,encodeClassicData_info(classicModbusData),"info")
        infoPublished = True

    mqttPublish(client,encodeClassicData_readings(classicModbusData),"readings")

def publishReadingsAndInfo(client):
    global snoozing, snoozeCount, infoPublished, wakeCount

    if snoozing:
        if (snoozeCount >= MQTT_SNOOZE_COUNT):
            infoPublished = False
            publish(client)
            snoozeCount = 0
        else:
            snoozeCount = snoozeCount + 1
    else:
        publish(client)
        wakeCount = wakeCount + 1
        if wakeCount >= WAKE_COUNT:
            snoozing = True
            wakeCount = 0
    

def modbus_periodic(modbus_stop):

    global classicModbusData
    if not modbus_stop.is_set():

        #Get the Modbus Data and store it.
        classicModbusData = getModbusData()

        # set myself to be called again in correct number of seconds
        threading.Timer(MODBUS_POLL_RATE, modbus_periodic, [modbus_stop]).start()

def mqtt_publish_periodic(mqtt_stop, client):
    # do something here ...
    if not mqtt_stop.is_set():

        publishReadingsAndInfo(client)
   
        # set myself to be called again in correct number of seconds
        threading.Timer(MQTT_PUBLISH_RATE, mqtt_publish_periodic, [mqtt_stop, client]).start()


def run():

    global doStop, mqttRoot

    #setup the MQTT Client for publishing and subscribing
    broker_address="islandmqtt.eastus.cloudapp.azure.com"     
    client = mqttclient.Client("Classic") #create new instance
    client.username_pw_set("glaserisland", password="R@staman1312")
    
    client.on_connect = on_connect    
    client.connect(broker_address) #connect to broker
    
    #setup command subscription
    client.on_message = on_message 
    client.subscribe("{}/classic/cmnd/#".format(mqttRoot))


    #loop on the receives
    client.loop_start()

    #define the stop for the function
    modbus_stop = threading.Event()

    # start calling f now and every 60 sec thereafter
    modbus_periodic(modbus_stop)

    #define the stop for the function
    mqtt_stop = threading.Event()

    # start calling f now and every 60 sec thereafter
    mqtt_publish_periodic(mqtt_stop, client)

    keepon = True
    while keepon:
        time.sleep(1)
        #check to see if shutdown received
        if doStop:
            keepon = False

    
    modbus_stop.set()
    mqtt_stop.set()
    client.loop_stop()


if __name__ == '__main__':
    run()