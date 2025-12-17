import time
import traceback
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID

# HA MQTT Python Lib: https://pypi.org/project/ha-mqtt-discoverable/
# nano /etc/systemd/system/energy-manager.service
# journalctl -u energy-manager -f
# systemctl status energy-manager
# source venv/bin/activate (from within cd opt/energy-manager)
# nano /opt/energy-manager/run.sh


print("Starting latest...")
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
        kwh_required_remaining=20, #kwh to be left in battery for overnight usage
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

    EC.MINIMUM_BATTERY_DISPATCH_PRICE = ha_mqtt.min_dispatch_price_number.value

update_sensors(amber.get_data())
# Code runs every 2 seconds (to reduce cpu usage)
def main_loop_code():
    global last_amber_update_timestamp, automatic_control
    ha_mqtt.alive_time_sensor.set_state(round(time.time()-start_time,1))

    if(time.time() - last_amber_update_timestamp > 30):
        amber_data = amber.get_data()
        last_amber_update_timestamp = time.time()
        print(f"Rate Limit Remaining: {amber.rate_limit_remaining}")
        update_sensors(amber_data)

        if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
            automatic_control = True
            EC.run(amber_data=amber_data)
        else: 
                print("Auto Control Off")

    if(ha.get_state("input_select.automatic_control_mode")["state"] != "On"):
        if(automatic_control == True):
                #EC.self_consumption()
                automatic_control = False
                print(f"Automatic Control turned off. Self Consumption mode active")
                ha.send_notification(f"Automatic Control turned off", "Self Consuming", "mobile_app_pixel_10_pro")

    
while True:
    try:
        if(ha_mqtt.controller_update_selector.state == "Update"):
            print("Update Commanded, exiting")
            break
        
        main_loop_code()
        
        time.sleep(2)
        
    except Exception as e:
        PrintError(e)
