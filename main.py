from machine import Pin
import time
import network
from umqtt.simple import MQTTClient
import urequests
import json
import gc

WIFI_SSID = "SSID"
WIFI_PASSWORD = "your password here"
DEBUG_ENABLED = False

# --- Pin Definitions ---
DS_PIN = 0      # Data Pin (DS/SER)
SHCP_PIN = 5    # Shift Clock Pin (SHCP)
STCP_PIN = 1    # Latch Clock Pin (STCP)
BUTTON1_PIN = 7
BUTTON2_PIN = 21
BUTTON3_PIN = 20
BUTTON4_PIN = 10
BUTTON5_PIN = 6
BUTTON6_PIN = 9
BUTTON7_PIN = 4

# URL definitions
BUTTON1_URL = 'http://192.168.77.215/relay/0?turn=toggle' # reflektor nad ZZ
BUTTON2_URL = 'http://192.168.77.215/relay/1?turn=toggle' # LED pasik pod strechou
BUTTON3_URL = 'http://192.168.77.219/relay/0?turn=toggle' # Svetla na garazi
BUTTON4_URL = 'http://192.168.77.116/color/0?turn=toggle' # LED pasik v ZZ
BUTTON5_URL = ''
BUTTON6_URL = 'http://192.168.77.219/relay/1?turn=toggle' # Gerazova brana
BUTTON7_URL = 'http://192.168.77.219/relay/2?turn=toggle' # Vonkajsia brana

#MQTT Topics
BUTTON1_TOPIC = b'shellies/shelly25-strecha/relay/0' # Reflektor nad ZZ
BUTTON2_TOPIC = b"shellies/shelly25-strecha/relay/1" # LED pasik pod strechou
#BUTTON3_TOPIC = b"shellypro3-garaz/#" # Svetla na garazi
BUTTON3_TOPIC = b"shellypro3-garaz/status/switch:0" # Svetla na garazi
#BUTTON3_TOPIC_2 = b"shellypro3-garaz/events/rpc" # Svetla na garazi - RPC
BUTTON4_TOPIC = b"shellies/shellyrgbw2zz/color/0" # LED pasik v ZZ
BUTTON6_TOPIC = b"/la92/garage_door_open" # Super ESP32 senzor na garazovu branu


# Register byte LED definitions
BUTTON1_BYTE = 0b00000001
BUTTON2_BYTE = 0b00000010
BUTTON3_BYTE = 0b00000100
BUTTON4_BYTE = 0b00010000
BUTTON5_BYTE = 0b00100000
BUTTON6_BYTE = 0b01000000
BUTTON7_BYTE = 0b10000000
LED_STATUS = 0b00000000 # current status to display (init value)
BLINK_MASK = 0b00000000

# MQTT definitions
MQTT_SERVER = 'your IP'
MQTT_USER = 'mqttuser'
MQTT_PASSWORD = 'mqttpassword'

LAST_UPDATE_TIMES = [0.0] * 8  
TIMEOUT_SECONDS = 600  # 10 minutes (60 * 10)
BLINK_PERIOD_MS = 500
last_blink_toggle_ms = time.ticks_ms()
toggle_bit = False

# Initialize the pins as outputs
data_pin = Pin(DS_PIN, Pin.OUT)
clock_pin = Pin(SHCP_PIN, Pin.OUT)
latch_pin = Pin(STCP_PIN, Pin.OUT)
button1_pin = Pin(BUTTON1_PIN,Pin.IN, Pin.PULL_UP)
button2_pin = Pin(BUTTON2_PIN,Pin.IN, Pin.PULL_UP)
button3_pin = Pin(BUTTON3_PIN,Pin.IN, Pin.PULL_UP)
button4_pin = Pin(BUTTON4_PIN,Pin.IN, Pin.PULL_UP)
button5_pin = Pin(BUTTON5_PIN,Pin.IN, Pin.PULL_UP)
button6_pin = Pin(BUTTON6_PIN,Pin.IN, Pin.PULL_UP)
button7_pin = Pin(BUTTON7_PIN,Pin.IN, Pin.PULL_UP)


def connect_to_wifi(ssid, password):
    """
    Connects the ESP32 to a specified Wi-Fi network with a running lights animation.
    """
    # Create a station interface object
    sta_if = network.WLAN(network.STA_IF)

    # Check if the interface is already active
    if not sta_if.active():
        sta_if.active(True)
        dprint("Wi-Fi interface activated.")

    # Check if already connected
    if sta_if.isconnected():
        dprint("Already connected.")
        dprint(f"IP address: {sta_if.ifconfig()[0]}")
        return sta_if.ifconfig()

    dprint(f"Connecting to Wi-Fi network: **{ssid}**...")
    
    # Try to connect - this starts the connection process in the background
    sta_if.connect(ssid, password)
    
    # --- Running Lights Animation Logic ---
    MAX_WAIT_MS = 10000  # Total wait time (10 seconds)
    ANIMATION_DELAY_MS = 100 # Speed of the running light (50ms per step)
    start_time_ms = time.ticks_ms()
    
    # Define the pattern to cycle through (B1 to B7)
    animation_pattern = [
        0b00000001, 0b00000010, 0b00000100, 0b00010000, 
        0b00100000, 0b01000000, 0b10000000
    ]
    pattern_index = 0
    
    # Loop until the connection succeeds or the total timeout is reached
    while time.ticks_diff(time.ticks_ms(), start_time_ms) < MAX_WAIT_MS:
        
        # Check connection status frequently (non-blocking)
        if sta_if.isconnected():
            break
            
        # 1. Update the LED pattern
        shift_out(animation_pattern[pattern_index])
        
        # 2. Advance the index for the next cycle (loops back to 0)
        pattern_index = (pattern_index + 1) % len(animation_pattern)
        
        # 3. Wait for the animation frame time
        time.sleep_ms(ANIMATION_DELAY_MS)
        
    # Ensure LEDs are turned off after the connection attempt
    shift_out(0b00000000)
    dprint() # Newline after the dots
    # --- End Running Lights Animation Logic ---

    if sta_if.isconnected():
        # Connection successful
        ip_info = sta_if.ifconfig()
        dprint("🎉 Connection successful!")
        dprint(f"IP address: {ip_info[0]}")
        dprint(f"Netmask: {ip_info[1]}")
        dprint(f"Gateway: {ip_info[2]}")
        dprint(f"DNS: {ip_info[3]}")
        return ip_info
    else:
        # Connection failed
        dprint("❌ Connection failed. Check SSID and Password.")
        # Deactivate the interface to save power (optional)
        sta_if.active(False)
        return None


def shift_out(data):
    """
    Sends an 8-bit byte to the shift register.
    """
    
    # 1. Lower the Latch pin to prepare for data
    latch_pin.value(0)
    
    # 2. Loop through 8 bits, MSB first
    for i in range(8):
        # Set the Data pin to the current bit value
        # The '& 0x80' masks all bits except the MSB.
        # The '>> i' shifts the bits to the right for the next iteration.
        data_pin.value((data >> (7 - i)) & 0x01) 
        
        # Pulse the Clock pin to shift the bit into the register
        clock_pin.value(1)
        clock_pin.value(0)
        
    # 3. Raise the Latch pin to transfer the data from the shift register
    #    to the storage/output register (Q0-Q7)
    latch_pin.value(1)
    
def dprint(*args, **kwargs):
    if DEBUG_ENABLED:
        print(*args, **kwargs)
        

def mqtt_callback(topic, msg):
    global LED_STATUS
    
    if topic == BUTTON1_TOPIC:
        print("Button1 topic incoming : " + str(topic))
        LAST_UPDATE_TIMES[0] = time.time()
        if msg.decode().lower() == 'on':
            LED_STATUS |= BUTTON1_BYTE
        if msg.decode().lower() == 'off':
            LED_STATUS = LED_STATUS & ~BUTTON1_BYTE
    
    if topic == BUTTON2_TOPIC:
        LAST_UPDATE_TIMES[1] = time.time()
        dprint("Button2 topic incoming : " + str(topic))
        if msg.decode().lower() == 'on':
            LED_STATUS |= BUTTON2_BYTE
        if msg.decode().lower() == 'off':
            LED_STATUS = LED_STATUS & ~BUTTON2_BYTE
      
    if topic == BUTTON3_TOPIC:
        LAST_UPDATE_TIMES[2] = time.time()
        dprint("Button3 topic incoming : " + str(topic))
        payload = json.loads(msg.decode())
        dprint("Button 3 payload: " + str(payload['output']))
        if payload['output'] is True:
            LED_STATUS |= BUTTON3_BYTE
        if payload['output'] is False:
            LED_STATUS = LED_STATUS & ~BUTTON3_BYTE
    
    """
    if topic == BUTTON3_TOPIC_2:
        dprint("Button3 rpc incoming :" + str(topic))
        payload = json.loads(msg.decode())
        if payload["params"]["switch:0"]["output"] is True:
            LED_STATUS |= BUTTON3_BYTE
        if payload["params"]["switch:0"]["output"] is False:
            LED_STATUS = LED_STATUS & ~BUTTON3_BYTE
    """


            
    if topic == BUTTON4_TOPIC:
        LAST_UPDATE_TIMES[3] = time.time()
        dprint("Button4 topic incoming : " + str(topic))
        dprint("Button 4 payload : " + msg.decode().lower())
        if msg.decode().lower() == 'on':
            LED_STATUS |= BUTTON4_BYTE
        if msg.decode().lower() == 'off':
            LED_STATUS = LED_STATUS & ~BUTTON4_BYTE
            
    if topic == BUTTON6_TOPIC:
        LAST_UPDATE_TIMES[5] = time.time()
        dprint("Button6 topic incoming")
        if msg.decode().lower() == '0':
            LED_STATUS |= BUTTON6_BYTE
        if msg.decode().lower() == '1':
            LED_STATUS = LED_STATUS & ~BUTTON6_BYTE

def reconnect_mqtt(client_id, server, port, user, password):
    print("Attempting MQTT reconnection...")
    try:
        new_client = MQTTClient(client_id, server, port=port, user=user, password=password, keepalive=60)
        new_client.set_callback(mqtt_callback)
        if new_client.connect() == 0:
            print("MQTT Reconnected successfully!")
            # Resubscribe to all topics here
            mqtt_client.subscribe(BUTTON1_TOPIC, qos=0) # Reflektor nad ZZ
            mqtt_client.subscribe(BUTTON2_TOPIC, qos=0) # LED pasik pod strechou
            mqtt_client.subscribe(BUTTON3_TOPIC, qos=0) # Svetla garaz
            #mqtt_client.subscribe(BUTTON3_TOPIC_2, qos=0) # Svetla garaz rpc
            mqtt_client.subscribe(BUTTON4_TOPIC, qos=0) # LED pasik v ZZ
            mqtt_client.subscribe(BUTTON6_TOPIC, qos=0) # senzor brany v garazi
            return new_client
        else:
            print("MQTT Reconnection failed.")
            return None
    except Exception as e:
        print(f"Error during reconnection: {e}")
        return None

# --- Main Loop ---
try:
    
    while True:
        try:
            print("--- Starting Connection Attempt ---")
        
            # 1. Wi-Fi Connection
            ip_config = connect_to_wifi(WIFI_SSID, WIFI_PASSWORD)
            if ip_config is None:
                # Raise an exception if connect_to_wifi fails its internal retries
                raise Exception("Wi-Fi connection failed.")

            # 2. MQTT Connection
            print(f"Attempting connection to MQTT server {MQTT_SERVER}...")
            mqtt_client = MQTTClient('arcade_remote', MQTT_SERVER, port=1883, user=MQTT_USER, password=MQTT_PASSWORD, keepalive=60)
            
            if mqtt_client.connect() != 0:
                raise Exception("MQTT connection failed.")
            
            print("MQTT Connected")
            mqtt_client.set_callback(mqtt_callback)
            
            # Subscribe to all topics here
            mqtt_client.subscribe(BUTTON1_TOPIC, qos=0) # Reflektor nad ZZ
            mqtt_client.subscribe(BUTTON2_TOPIC, qos=0) # LED pasik pod strechou
            mqtt_client.subscribe(BUTTON3_TOPIC, qos=0) # Svetla garaz
            #mqtt_client.subscribe(BUTTON3_TOPIC_2, qos=0) # Svetla garaz rpc
            mqtt_client.subscribe(BUTTON4_TOPIC, qos=0) # LED pasik v ZZ
            mqtt_client.subscribe(BUTTON6_TOPIC, qos=0) # senzor brany v garazi
            

            # 🎉 If all steps succeed, exit the loop and move to the main program execution
            print("✅ Setup complete! Proceeding to main loop.")
            break
            

        except Exception as e:
            print(f"❌ Initial setup failed: {e}.")
            print(f"Retrying connection in 10 seconds...")
            
            # Clean up client object if it exists but failed to connect
            try:
                if 'mqtt_client' in locals() and mqtt_client is not None:
                    mqtt_client.disconnect()
            except:
                pass # Ignore errors during disconnect attempt
            
            # Sleep for a reasonable time before the next retry
            time.sleep(10)
            # The loop will automatically start the setup sequence again (Wi-Fi first)
    
  
        
    PING_INTERVAL_CYCLES = 100 
    ping_counter = 0
    

    print("Starting LED toggle via Shift Register...")
    shift_out(LED_STATUS)
    
    while True:
        
        try:
            mqtt_client.check_msg()
            ping_counter += 1
            if ping_counter >= PING_INTERVAL_CYCLES:
                try:
                    mqtt_client.ping()
                    gc.collect()
                    dprint("** Mqtt ping + gc.collect() ** ")
                except Exception as e:
                    print(f"Ping failed: {e}")
                ping_counter = 0
        except OSError as e:
            print(f"Connection lost or socket error: {e}. Initiating recovery.")
            time.sleep(5)
            # If reconnection fails, the loop continues to hit the OSError,
            # which forces another 5s wait and another retry.
            if not reconnect_mqtt():
                time.sleep(5) 
            continue # Go back to the start of the while loop
        
        
        # *** Blinking logic : if we don't get updates over mqtt - we'll start blinking that particular button
        current_time = time.time()
        BLINK_MASK = 0b00000000  # Reset mask every cycle
        
        UPDATE_MAPPING = {
            0: BUTTON1_BYTE,
            1: BUTTON2_BYTE,
            2: BUTTON3_BYTE,
            3: BUTTON4_BYTE, # Note: Index 3 maps to Bit 4
            5: BUTTON6_BYTE  # Note: Index 5 maps to Bit 6 (FIXED)
        }

        for i in UPDATE_MAPPING:
        # Check if the time elapsed exceeds the timeout
            if current_time - LAST_UPDATE_TIMES[i] > TIMEOUT_SECONDS:
                # If it timed out, set the corresponding bit in the BLINK_MASK
                BLINK_MASK |= UPDATE_MAPPING[i]
        current_ms = time.ticks_ms()
        if time.ticks_diff(current_ms, last_blink_toggle_ms) >= BLINK_PERIOD_MS:
            toggle_bit = not toggle_bit
            last_blink_toggle_ms = current_ms
        final_shift_register_value = LED_STATUS
        
        if toggle_bit is True:
        # If the toggle is ON, flip the state of only the timed-out bits (XOR with BLINK_MASK)
        # If a bit in LED_STATUS is 1 and BLINK_MASK is 1, it flips to 0 (off)
        # If a bit in LED_STATUS is 0 and BLINK_MASK is 1, it flips to 1 (on)
            final_shift_register_value ^= BLINK_MASK
        else:
        # If the toggle is OFF, the timed-out LEDs revert to their last reported state.
        # Note: If the last reported state was OFF, it will stay OFF, resulting in a 50% duty cycle blink.
            pass
        # *** end blinking logic
    
        
        button1_state=button1_pin.value()
        button2_state=button2_pin.value()
        button3_state=button3_pin.value()
        button4_state=button4_pin.value()
        button5_state=button5_pin.value()
        button6_state=button6_pin.value()
        button7_state=button7_pin.value()



        if button1_state == 0:
            http_req = None
            try:
                http_req = urequests.get(BUTTON1_URL, headers={'Content-Type': 'application/json'})
                #time.sleep(0.1)
            except Exception as e:
                print(f"HTTP error for Button1: {e}")
            finally:
                if http_req:
                    http_req.close()
        if button2_state == 0:
            http_req = None
            try:
                http_req = urequests.get(BUTTON2_URL, headers={'Content-Type': 'application/json'})
            except Exception as e:
                print(f"HTTP error for Button2: {e}")
            finally:
                if http_req:
                    http_req.close()
        if button3_state == 0:
            http_req = None
            try:
                http_req = urequests.get(BUTTON3_URL, headers={'Content-Type': 'application/json'})
            except Exception as e:
                print(f"HTTP error for Button3: {e}")
            finally:
                if http_req:
                    http_req.close()
        if button4_state == 0:
            http_req = None
            try:
                http_req = urequests.get(BUTTON4_URL, headers={'Content-Type': 'application/json'})
            except Exception as e:
                print(f"HTTP error for Button4: {e}")
            finally:
                if http_req:
                    http_req.close()
        if button5_state == 0:
            LED_STATUS ^= BUTTON5_BYTE
            # http_req = urequests.get(BUTTON5_URL, headers={'Content-Type': 'application/json'})
        if button6_state == 0:
            http_req = None
            try:
                http_req = urequests.get(BUTTON6_URL, headers={'Content-Type': 'application/json'})
            except Exception as e:
                print(f"HTTP error for Button6: {e}")
            finally:
                if http_req:
                    http_req.close()
        if button7_state == 0:
            shift_out(BUTTON7_BYTE)
            http_req = None
            try:
                http_req = urequests.get(BUTTON7_URL, headers={'Content-Type': 'application/json'})
            except Exception as e:
                print(f"HTTP error for Button7: {e}")
            finally:
                if http_req:
                    http_req.close()
                    
        shift_out(final_shift_register_value)
        time.sleep(0.1) #final main while loop sleep (to slow down loop & debounce)
        
     

except KeyboardInterrupt:
    print("\nStopping loop and clearing outputs.")
    # Ensure all outputs are off upon exit
    shift_out(0)
