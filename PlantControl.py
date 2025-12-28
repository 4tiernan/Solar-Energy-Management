from ha_api import HomeAssistantAPI
from dataclasses import dataclass
import datetime
from zoneinfo import ZoneInfo
import time
import numpy as np
import math

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
        self.max_discharge_power = 24
        self.max_charge_power = 21
        self.max_pv_power = 24
        self.max_export_power = 15
        self.max_import_power = 45

        self.last_load_data_retrival_timestamp = 0
        self.avg_load_day = None

        self.last_base_load_estimate_timestamp = 0
        self.base_load_estimate = None

        self.update_data()
    def get_plant_mode(self):
        return self.ha.get_state("select.sigen_plant_remote_ems_control_mode")["state"]

    def update_data(self):
        self.kwh_backup_buffer = (self.ha.get_numeric_state("number.sigen_plant_ess_backup_state_of_charge")/100.0) * self.rated_capacity
        self.kwh_stored_energy = self.ha.get_numeric_state("sensor.sigen_plant_available_max_discharging_capacity")
        self.kwh_stored_available = self.kwh_stored_energy - self.kwh_backup_buffer
        self.kwh_charge_unusable = (1-(self.ha.get_numeric_state("number.sigen_plant_ess_charge_cut_off_state_of_charge")/100.0)) * self.rated_capacity # kWh of buffer to 100% IE the charge limit 
        self.kwh_till_full = self.ha.get_numeric_state("sensor.sigen_plant_available_max_charging_capacity") - self.kwh_charge_unusable
        self.battery_kw = self.ha.get_numeric_state("sensor.reversed_battery_power")

        self.solar_kw = self.ha.get_numeric_state("sensor.sigen_plant_pv_power")
        self.solar_kwh_today = self.ha.get_numeric_state("sensor.sigen_inverter_daily_pv_energy")
        self.solar_kw_remaining_today = self.ha.get_numeric_state("sensor.solcast_pv_forecast_forecast_remaining_today")
        self.solar_daytime = self.ha.get_numeric_state('sensor.solcast_pv_forecast_forecast_this_hour') > self.get_base_load_estimate() # If producing more power than base load consider it during the solar day
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
    
    def calculate_base_load(self, days_ago = 7): # Calculate base load in kW
        today = datetime.datetime.now(HA_TZ).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=HA_TZ)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=HA_TZ)

        load_state_history = self.ha.get_history("sensor.sigen_plant_consumed_power", start_time=start, end_time=end)

        load_history = [h.state for h in load_state_history]
        
        load_history_clean = [
            v for v in load_history
            if v is not None and not math.isnan(v)
        ]
        self.base_load_estimate = np.percentile(load_history_clean, 20)

        return self.base_load_estimate
    
    def get_base_load_estimate(self, days_ago = 7, hours_update_interval=24): # Returns approximate base load in kW
        if(time.time() - self.last_base_load_estimate_timestamp > hours_update_interval*60*60 or self.base_load_estimate == None):
            self.base_load_estimate = self.calculate_base_load(days_ago)
            self.last_base_load_estimate_timestamp = time.time()
        return self.base_load_estimate

        

    def update_load_avg(self, days_ago=7):
        today = datetime.datetime.now(HA_TZ).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=HA_TZ)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=HA_TZ)


        history = self.ha.get_history("sensor.sigen_plant_daily_load_consumption", start_time=start, end_time=end)
        #print(f"start: {start}  \n end: {end}\nhistory: {history[2].time.date()}")

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
                    minute=(state.time.minute // time_bucket_size) * time_bucket_size,
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
                    if(state.state != None):
                        bin_avg.append(state.state)
            if(len(bin_avg) > 0):                    
                avg_day[i].states.append(sum(bin_avg) / len(bin_avg))   # calc avg for last period of day 

        for interval in avg_day:
            if(len(interval.states) == 0):
                raise Exception(f"Failed to get state data for {state.time} time period")
            interval.state = round(sum(interval.states) / len(interval.states), 2)

        #for i in range(len(avg_day)): # Print average for each day and each time
        #    print(avg_day[i].state)
        #    print(avg_day[i].states)       

        return avg_day
    
    def get_load_avg(self, days_ago, hours_update_interval=24): # hours_update_interval: frequency to update the load date
        if(time.time() - self.last_load_data_retrival_timestamp > hours_update_interval*60*60 or self.avg_load_day == None):
            self.avg_load_day = self.update_load_avg(days_ago)
            self.last_load_data_retrival_timestamp = time.time()
        return self.avg_load_day
        
    def forecast_consumption_amount(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=7)
        rounded_current_time = self.round_minutes(datetime.datetime.now(), nearest_minute=5)
        if(forecast_hours_from_now):
            rounded_forecast_time = self.round_minutes(rounded_current_time + datetime.timedelta(hours=forecast_hours_from_now), nearest_minute=5).time()
        elif(forecast_till_time):
            rounded_forecast_time = self.round_minutes(forecast_till_time, nearest_minute=5)
        else:
            raise Exception("Must provide forecast hours or time to determine forecast!")
        
        rounded_current_time = rounded_current_time.time()

        starting_kwh = None
        ending_kwh = None
        for bin in avg_day:
            #print(f"time: {bin.time} state: {bin.state}")
            if(bin.time == rounded_current_time):
                
                starting_kwh = bin.state
            elif(starting_kwh != None and bin.time == rounded_forecast_time):
                ending_kwh = bin.state
        
        if(ending_kwh == None):
            for bin in avg_day:
                if(bin.time == rounded_forecast_time):
                    ending_kwh = bin.state + avg_day[-1].state # If the number of hours wraps past midnight, add the last state from the previous day to the total kwh
        
        return ending_kwh-starting_kwh
    
    def kwh_required_remaining(self, buffer=5):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(6, 0, 0))
        return max(forecast_kwh, 0) + buffer
        
    def round_minutes(self, time, nearest_minute):
        return time.replace(
            minute=(time.minute // nearest_minute) * nearest_minute,
            second=0,
            microsecond=0,
            tzinfo=HA_TZ
            )  

#from api_token_secrets import HA_URL, HA_TOKEN
#plant = Plant(HA_URL, HA_TOKEN, errors=True) 
#print(plant.get_base_load_estimate())
#print(plant.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0)))
