import time
import datetime
import traceback
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID

# HA MQTT Python Lib: https://pypi.org/project/ha-mqtt-discoverable/
# nano /etc/systemd/system/energy-manager.service
# journalctl -u energy-manager -f
# journalctl -u energy-manager -n 10000 -f
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
        buffer_percentage_remaining=35, # percentage to inflate predicted load consumption
    )

except Exception as e:
    PrintError(e)


start_time = time.time()
last_amber_update_timestamp = 0
automatic_control = True # var to keep track of whether the auto control switch is on

next_amber_update_timestamp = time.time() #time to run the next amber update
partial_update = False #Indicates wheather to do a full amber update or just the current prices (if only estimated prices)
amber_data = amber.get_data()

def determine_effective_price(amber_data):
    general_price = amber_data.general_price
    feedIn_price = amber_data.feedIn_price
    target_dispatch_price = EC.target_dispatch_price
    remaining_solar_today = plant.solar_kw_remaining_today
    forecast_load_till_morning = EC.kwh_required_remaining

    base_load = plant.get_base_load_estimate() # kW estimated base load
    solar_daytime = plant.solar_daytime # If producing more power than base load consider it during the solar day
    available_energy = max(remaining_solar_today-10, 0) + plant.kwh_stored_available # kWh of energy available right now
    energy_consumption_available = plant.kwh_till_full + plant.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0)) # kWh that can be used of the available solar

    effective_dispatch_price = max(target_dispatch_price, feedIn_price)

    if(general_price < 0):
        return general_price
    elif(solar_daytime): # Solar > base load estimate
        if(remaining_solar_today > energy_consumption_available): # There should be excess power that would be sold at the feed in price or wasted
            return max(feedIn_price, 0)
        elif(available_energy > forecast_load_till_morning): # Energy used will cut into feed in profits 
            return effective_dispatch_price
        else:
            return general_price
    else: # Not solar daytime
        if(plant.kwh_stored_available > forecast_load_till_morning): # More battery than required overnight, energy use will cut into feed in profits
            return effective_dispatch_price
        else:
            return general_price # default to the general price


# Update HA MQTT sensors
def update_sensors(amber_data):
    EC.update_values(amber_data=amber_data)
    ha_mqtt.max_feedIn_sensor.set_state(round(amber_data.feedIn_max_forecast_price))
    ha_mqtt.current_feedIn_sensor.set_state(round(amber_data.feedIn_price))
    ha_mqtt.current_general_price_sensor.set_state(round(amber_data.general_price))
    ha_mqtt.kwh_discharged_sensor.set_state(round(plant.kwh_till_full, 2))
    ha_mqtt.kwh_remaining_sensor.set_state(round(plant.kwh_stored_available, 2))
    ha_mqtt.target_discharge_sensor.set_state(round(EC.target_dispatch_price))
    ha_mqtt.kwh_required_overnight_sensor.set_state(round(EC.kwh_required_remaining, 2))
    ha_mqtt.amber_api_calls_remaining_sensor.set_state(amber.rate_limit_remaining)
    ha_mqtt.working_mode_sensor.set_state(EC.working_mode)
    grid_export_power = round(ha.get_numeric_state("sensor.sigen_plant_grid_export_power"), 2)
    ha_mqtt.system_state_sensor.set_state(EC.working_mode + f" {grid_export_power} @ {amber_data.feedIn_price} c/kWh")
    ha_mqtt.base_load_sensor.set_state(1000*plant.get_base_load_estimate()) # converted to w from kW
    ha_mqtt.effective_price_sensor.set_state(determine_effective_price(amber_data)) 

    EC.MINIMUM_BATTERY_DISPATCH_PRICE = ha_mqtt.min_dispatch_price_number.value

update_sensors(amber_data)
time.sleep(1)
print("Configuration complete. Running")

# Code runs every 2 seconds (to reduce cpu usage)
def main_loop_code():
    global automatic_control, next_amber_update_timestamp, partial_update, amber_data

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
            real_price_offset = 20 # seconds after the period begins when the real price starts
            now_datetime = datetime.datetime.now()
            seconds_till_next_update = 300 - ((now_datetime.minute * 60 + now_datetime.second) % 300) + real_price_offset
    
            if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
                automatic_control = True
                EC.run(amber_data=amber_data)

        print(f"Partial Update: {partial_update}")
        print(f"Seconds till next update: {seconds_till_next_update}")
        next_amber_update_timestamp = time.time() + seconds_till_next_update

    update_sensors(amber_data)

    if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
        automatic_control = True
        EC.mainain_control_mode() # Maintain the control mode (mainly for export all solar)

        

    if(ha.get_state("input_select.automatic_control_mode")["state"] != "On"):
        if(automatic_control == True):
            #EC.self_consumption()
            automatic_control = False
            print(f"Automatic Control turned off.")
            ha.send_notification(f"Automatic Control turned off", "Self Consuming", "mobile_app_pixel_10_pro")

    elif(ha.get_state("input_select.automatic_control_mode")["state"] == "On" and automatic_control == False):
                automatic_control = True
                print(f"Automatic Control turned on.")
                EC.run(amber_data=amber_data)
                
            
    
while True:
    try:
        if(ha_mqtt.controller_update_selector.state == "Update"):
            print("Update Commanded, exiting")
            break
        
        main_loop_code()
        time.sleep(2)

        ha_mqtt.alive_time_sensor.set_state(round(time.time()-start_time,1))
        
    except Exception as e:
        PrintError(e)
