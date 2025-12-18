import time
import datetime
import traceback
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID

# HA MQTT Python Lib: https://pypi.org/project/ha-mqtt-discoverable/
# nano /etc/systemd/system/energy-manager.service
# journalctl -u energy-manager -f
# systemctl status energy-manager
# source venv/bin/activate (from within cd opt/energy-manager)
# nano /opt/energy-manager/run.sh


print("Starting...")
started = False

def PrintError(e):
    print(f"Exception occoured: {e}")
    traceback.print_exc() # Prints the full traceback to the console
    print("Trying again after 30 seconds")
    time.sleep(30)

while(started == False):
    try:
        from energy_controller import EnergyController
        from ha_api import HomeAssistantAPI
        import ha_mqtt
        from amber_api import AmberAPI
        import PlantControl
        started = True
    except Exception as e:
        PrintError(e)
        

try: 
    amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)
    amber_data = amber.get_data()
    last_amber_update_timestamp = time.time()

    plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 

    ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )
    ha_mqtt.controller_update_selector.set_state("Working")

    EC = EnergyController(
        ha=ha,
        ha_mqtt=ha_mqtt,
        plant=plant,
        kwh_buffer_remaining=5, #kwh to be left in battery after forecasted usage
        good_sell_price=50 #price it is worth potentially running flat for
    )

except Exception as e:
    PrintError(e)


print("Configuration complete. Running")
start_time = time.time()
last_amber_update_timestamp = 0
automatic_control = True # var to keep track of whether the auto control switch is on

# Update HA MQTT sensors
def update_sensors(amber_data):
    ha_mqtt.max_feedIn_sensor.set_state(round(amber_data.feedIn_max_forecast_price))
    ha_mqtt.current_feedIn_sensor.set_state(round(amber_data.feedIn_price))
    ha_mqtt.current_general_price_sensor.set_state(round(amber_data.general_price))
    ha_mqtt.kwh_discharged_sensor.set_state(round(plant.kwh_till_full, 2))
    ha_mqtt.kwh_remaining_sensor.set_state(round(plant.kwh_stored_available, 2))
    ha_mqtt.target_discharge_sensor.set_state(round(EC.target_dispatch_price))
    ha_mqtt.kwh_required_overnight_sensor.set_state(round(EC.kwh_required_remaining, 2))
    ha_mqtt.amber_api_calls_remaining_sensor.set_state(amber.rate_limit_remaining)

    EC.MINIMUM_BATTERY_DISPATCH_PRICE = ha_mqtt.min_dispatch_price_number.value

update_sensors(amber.get_data())

next_amber_update_timestamp = time.time() #time to run the next amber update
partial_update = False #Indicates wheather to do a full amber update or just the current prices (if only estimated prices)

# Code runs every 2 seconds (to reduce cpu usage)
def main_loop_code():
    global automatic_control, next_amber_update_timestamp, partial_update
    ha_mqtt.alive_time_sensor.set_state(round(time.time()-start_time,1))


    if(time.time() >= next_amber_update_timestamp):
        if(partial_update):
            amber_data = amber.get_data(partial_update=True)
        else:
            amber_data = amber.get_data()

        if(amber_data.prices_estimated):
            seconds_till_next_update = 10
            partial_update = True # Make the next update a partial one
        else:
            partial_update = False
            real_price_offset = 10 # seconds after the period begins when the real price starts
            now_datetime = datetime.datetime.now()
            seconds_till_next_update = 305 - ((now_datetime.minute * 60 + now_datetime.second) % 300)
            EC.update_values(amber_data=amber_data)
            update_sensors(amber_data)
            if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
                automatic_control = True
                EC.run(amber_data=amber_data)

        print(f"Partial Update: {partial_update}")
        print(f"Seconds till next update: {seconds_till_next_update}")
        next_amber_update_timestamp = time.time() + seconds_till_next_update
              

        

    if(ha.get_state("input_select.automatic_control_mode")["state"] != "On"):
        if(automatic_control == True):
                #EC.self_consumption()
                automatic_control = False
                print(f"Automatic Control turned off. Self Consumption mode active")
                ha.send_notification(f"Automatic Control turned off", "Self Consuming", "mobile_app_pixel_10_pro")
        print("Auto Control Off")
            
    
while True:
    try:
        if(ha_mqtt.controller_update_selector.state == "Update"):
            print("Update Commanded, exiting")
            break
        
        main_loop_code()
        
        time.sleep(2)
        
    except Exception as e:
        PrintError(e)
