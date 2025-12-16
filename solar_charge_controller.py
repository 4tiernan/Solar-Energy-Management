from datetime import datetime, timedelta, time
from ha_api import HomeAssistantAPI
from api_token_secrets import HA_URL, HA_TOKEN

ha = HomeAssistantAPI(
    base_url=HA_URL,
    token=HA_TOKEN,
    errors=True
)



# Call a service
#ha.call_service("switch", "turn_off", {"entity_id": "switch.sigen_plant_remote_ems_controled_by_home_assistant"})
#ha.set_switch_state("switch.sigen_plant_remote_ems_controled_by_home_assistant", False)
#ha.set_number("number.sigen_plant_ess_max_discharging_limit", 15)

# Get entity state
print(str(ha.get_numeric_state("sensor.sigen_plant_battery_state_of_charge"))+"%")


rated_capacity = ha.get_numeric_state("sensor.sigen_plant_rated_energy_capacity")

kwh_stored_energy = ha.get_numeric_state("sensor.sigen_plant_available_max_discharging_capacity")
kwh_backup_buffer = (ha.get_numeric_state("number.sigen_plant_ess_backup_state_of_charge")/100.0) * rated_capacity
kwh_stored_available = kwh_stored_energy - kwh_backup_buffer

print("Stored Energy: "+str(round(kwh_stored_energy,2))+" kWh")
print("Available Stored Energy: "+str(round(kwh_stored_available,2))+" kWh")

kwh_till_full = ha.get_numeric_state("sensor.sigen_plant_available_max_charging_capacity")

print("kWh till Full: "+str(round(kwh_till_full,2))+" kWh")

battery_kW = ha.get_numeric_state("sensor.reversed_battery_power")

if(battery_kW < 0):
    hrs_till_full = kwh_till_full/abs(battery_kW)
    minutes = 0
    hrs = 0
    if(hrs_till_full < 1):
        minutes = hrs_till_full/60.0
    else:
        minutes = hrs_till_full % 60
        hrs = int(hrs_till_full)


    print(str(round(hrs,2))+" hrs "+str(round(minutes))+" mintues till full")

    current_time = datetime.now()
    charged_time = current_time + timedelta(hours=hrs_till_full)
    print(f"Charged time: {charged_time}")


    target_charged_time = datetime.combine(current_time, time(15,0))
    if current_time < target_charged_time:
        hrs_until_target = (target_charged_time - current_time).total_seconds() / 3600
        print(str(round(hrs_until_target,2))+" hrs until target time")

        required_charge_rate = kwh_till_full / hrs_until_target
        print("Required Charge Rate: "+str(round(required_charge_rate, 2))+" kW")
        #ha.set_number("number.sigen_plant_ess_max_charging_limit", round(required_charge_rate,1))
        #print("Set max charge rate to "+str(round(required_charge_rate,1))+" kW")
