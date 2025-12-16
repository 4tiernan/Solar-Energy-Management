from ha_api import HomeAssistantAPI
from dataclasses import dataclass
import datetime
from zoneinfo import ZoneInfo

HA_TZ = ZoneInfo("Australia/Brisbane") 

@dataclass
class StateClass:
    states: list[float]
    state: float
    time: datetime

class Plant:
    def __init__(self, HA_URL, TOKEN, errors=True):
        self.ha = HomeAssistantAPI(
            base_url=HA_URL,
            token=TOKEN,
            errors=errors
        )
        self.control_mode_options = [
            "Standby",
            "Maximum Self Consumption",
            "Command Charging (PV First)",
            "Command Charging (Grid First)",
            "Command Discharging (PV First)",
            "Command Discharging (ESS First)"]
        self.rated_capacity = self.ha.get_numeric_state("sensor.sigen_plant_rated_energy_capacity")
        self.max_discharge_power = 21
        self.max_charge_power = 21
        self.max_pv_power = 21
        self.max_export_power = 21
        self.max_import_power = 21
        self.update_data()
    def get_plant_mode(self):
        return self.ha.get_state("select.sigen_plant_remote_ems_control_mode")["state"]

    def update_data(self):
        self.kwh_backup_buffer = (self.ha.get_numeric_state("number.sigen_plant_ess_backup_state_of_charge")/100.0) * self.rated_capacity
        self.kwh_stored_energy = self.ha.get_numeric_state("sensor.sigen_plant_available_max_discharging_capacity")
        self.kwh_stored_available = self.kwh_stored_energy - self.kwh_backup_buffer
        self.kwh_till_full = self.ha.get_numeric_state("sensor.sigen_plant_available_max_charging_capacity")
        self.battery_kw = self.ha.get_numeric_state("sensor.reversed_battery_power")

        self.solar_kw = self.ha.get_numeric_state("sensor.sigen_plant_pv_power")
        self.solar_kwh_today = self.ha.get_numeric_state("sensor.sigen_inverter_daily_pv_energy")
        self.solar_kw_remaining_today = self.ha.get_numeric_state("sensor.solcast_pv_forecast_forecast_remaining_today")

        self.inverter_power = self.ha.get_numeric_state("sensor.sigen_plant_plant_active_power")
        self.grid_power = self.ha.get_numeric_state("sensor.sigen_plant_grid_active_power")

        self.hours_till_full = 0
        self.hours_till_empty = 0
        if(self.battery_kw < 0):
            self.hours_till_full = round(self.kwh_till_full / abs(self.battery_kw), 2)
        elif(self.battery_kw > 0):
            self.hours_till_empty = round(self.kwh_stored_available / abs(self.battery_kw), 2)

    def display_data(self):
        self.update_data()
        print("Stored Energy: "+str(round(self.kwh_stored_energy,2))+" kWh")
        print("Available Stored Energy: "+str(round(self.kwh_stored_available,2))+" kWh")
        print("kWh till Full: "+str(round(self.kwh_till_full,2))+" kWh")
        print(f"Hours Till Full: {self.display_hrs_minutes(self.hours_till_full)}")
        print(f"Hours Till Empty: {self.display_hrs_minutes(self.hours_till_empty)}")

    def display_hrs_minutes(self, hours):
        if(hours < 1):
            return f"{round(hours*60)} minutes"
        elif(hours%1 == 0):
            return f"{int(hours)} hours"
        else:   
            return f"{int(hours)} hours {round((hours%1)*60)} minutes"


    def update_ha_monitoring_entities():
        raise("SET THIS UP")
        #time till full/empty


    def set_control_limits(self, control_mode, discharge, charge, pv, grid_export, grid_import):
        #if(self.get_plant_mode() != control_mode):
        self.ha.set_number("number.sigen_plant_ess_max_discharging_limit", discharge)
        self.ha.set_number("number.sigen_plant_ess_max_charging_limit", charge)
        self.ha.set_number("number.sigen_plant_pv_max_power_limit", pv)
        self.ha.set_number("number.sigen_plant_grid_export_limitation", grid_export)
        self.ha.set_number("number.sigen_plant_grid_import_limitation", grid_import)
        
        if(control_mode in self.control_mode_options):
            self.ha.set_select("select.sigen_plant_remote_ems_control_mode", control_mode)
        else:
            raise(f"Requested control mode '{control_mode}' is not a valid control mode!")


    def get_load_avg(self, days_ago):
        today = datetime.datetime.now(HA_TZ).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=HA_TZ)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=HA_TZ)


        history = self.ha.get_history("sensor.sigen_plant_daily_load_consumption", start_time=start, end_time=end)
        print(f"start: {start}  \n end: {end}\nhistory: {history[2].time.date()}")

        day = 0
        history_days = [[]]
        for hist in history: 
            if(hist.time.date() == start_date + datetime.timedelta(days=day)):
                history_days[day].append(hist)
            elif(hist.time.date() == start_date + datetime.timedelta(days=day+1)):
                day = day + 1
                history_days.append([])
                history_days[day].append(hist)

        for day in history_days:
            while(day[0].state > 0.05): # remove any states that were from the previous day, ie ensure we start with 0 for the day
                day.pop(0)

        avg_day = []
        dt = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time.min
        )
        time_bucket_size = 5 # Size of time bucket in Minutes 
        for i in range(int((24*60)/time_bucket_size)):
            avg_day.append(StateClass(state=None, states=[], time=dt.time()))
            dt = dt + datetime.timedelta(minutes=time_bucket_size)
        
        
        for day in history_days:
            i = 0
            bin_avg = []
            for state in day: 
                state.time = state.time.replace(
                    minute=(state.time.minute // 5) * 5,
                    second=0,
                    microsecond=0,
                    tzinfo=HA_TZ
                    )
                
                if(state.time.time() != avg_day[i].time):
                    if(i < len(avg_day)-1):
                        if(state.time.time() == avg_day[i+1].time):
                            avg_day[i].states.append(sum(bin_avg) / len(bin_avg))
                            bin_avg = []
                            i = i + 1

                if(state.time.time() == avg_day[i].time):
                    bin_avg.append(state.state)
                                
            avg_day[i].states.append(sum(bin_avg) / len(bin_avg))   # calc avg for last period of day 

        for interval in avg_day:
            if(len(interval.states) == 0):
                raise Exception(f"Failed to get state data for {state.time} time period")
            interval.state = round(sum(interval.states) / len(interval.states), 2)

        #for i in range(len(avg_day)): # Print average for each day and each time
        #    print(avg_day[i].state)
        #    print(avg_day[i].states)       

        return avg_day
     
        
    def forecast_consumption_amount(self, hours):
        avg_day = self.get_load_avg(days_ago=7)
        
        


plant = Plant(HA_URL, TOKEN, errors=True) 
plant.get_load_avg(3)