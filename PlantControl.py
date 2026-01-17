from ha_api import HomeAssistantAPI
from dataclasses import dataclass
import datetime
from zoneinfo import ZoneInfo
import time
import numpy as np
import math
import pandas as pd


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
        self.load_avg_days = 3

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
        self.load_power = self.ha.get_numeric_state("sensor.sigen_plant_consumed_power")
        self.avg_daily_load = self.get_load_avg(days_ago=self.load_avg_days)[-1].state
        
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
    
    def check_control_limits(self, working_mode, control_mode, discharge, charge, pv, grid_export, grid_import):
        current_control_mode = self.get_plant_mode()
        curent_discharge_limit = self.ha.get_numeric_state("number.sigen_plant_ess_max_discharging_limit")
        curent_charge_limit = self.ha.get_numeric_state("number.sigen_plant_ess_max_charging_limit")
        curent_pv_limit = self.ha.get_numeric_state("number.sigen_plant_pv_max_power_limit")
        curent_export_limit = self.ha.get_numeric_state("number.sigen_plant_grid_export_limitation")
        curent_import_limit = self.ha.get_numeric_state("number.sigen_plant_grid_import_limitation")

        a = current_control_mode != control_mode or curent_discharge_limit != discharge or curent_charge_limit != charge
        b = curent_pv_limit != pv or curent_export_limit != grid_export or curent_import_limit != grid_import

        if(a or b):
            self.set_control_limits(control_mode, discharge, charge, pv, grid_export, grid_import)
            print(f"{working_mode} !!!")
            time.sleep(5) # Allow time for HA to update

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

        # Remove any invalid states from the history list (Unavailable, None, etc)
        clean_history = []
        for hist in history:
            try:
                if hist.state is not None:
                    hist.state = float(hist.state)
                    clean_history.append(hist)
            except (ValueError, TypeError):
                pass  # drop unknown/unavailable/etc
        

        day = 0
        history_days = [[]]
        for hist in clean_history: 
            if(hist.time.date() == start_date + datetime.timedelta(days=day)):
                history_days[day].append(hist)
            elif(hist.time.date() == start_date + datetime.timedelta(days=day+1)):
                day = day + 1
                history_days.append([])
                history_days[day].append(hist)

        for day in history_days:
            day_states = [d.state for d in day]
            min_state = min(day_states[0:int(len(day_states)/2)]) # Minimum state for first half of day (avoids getting next days minimum)
            max_state = min(day_states[int(len(day_states)/2):-1]) # Maximum state for second half of day (avoids getting next days minimum)

            while(day[0].state > min_state): # remove any states that were from the previous day, ie ensure we start with 0 for the day
                day.pop(0)
                #print("Popping Start of Day Data")
            
            while(day[-1].state < max_state): # remove any states that were from the previous day, ie ensure we start with 0 for the day
                day.pop(-1)
                #print("Popping End of Day Data")



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
                # Round the state's time to the nearest time bin
                state.time = state.time.replace(
                    minute=(state.time.minute // time_bucket_size) * time_bucket_size,
                    second=0,
                    microsecond=0,
                    tzinfo=HA_TZ
                    )
                                
                # If it doesn't match, then it should belong in the next bin, thus increment to the next bin
                if(state.time.time() != avg_day[i].time): 
                    if(i < len(avg_day)-1):
                        if(state.time.time() == avg_day[i+1].time):
                            if(len(bin_avg) > 0):
                                avg_day[i].states.append(sum(bin_avg) / len(bin_avg)) # Append the average for this day's time bin
                            else:
                                avg_day[i].states.append(None) # Make the state 0 if we have no data for it 
                            bin_avg = []
                            i = i + 1
                        else: # If the time we are after isn't in the next bin then there musn't be data there
                            avg_day[i].states.append(None) # Make the state 0 if we have no data for it 
                            i = i + 1

                # If the state's rounded time matches the current array time bin, add it to the array
                if(state.time.time() == avg_day[i].time):
                    if(state.state != None):
                        bin_avg.append(state.state)

            if(len(bin_avg) > 0):                    
                avg_day[i].states.append(sum(bin_avg) / len(bin_avg))   # calc avg for last period of day         

        #for interval in avg_day:
        #    print(interval.states)
        
        for index, interval in enumerate(avg_day):
            for state_index, state in enumerate(avg_day[index].states): # Check all days states for that time have data
                if(state == None): # If there's no data for that day's state, take the avg of the last and next states for that day
                    last_state = None
                    next_state = None
                    lower_idx = index - 1
                    while(last_state == None and lower_idx > 1): # Find the last two valid states for that day (2 states increases likelyhood they are vaild)
                        if(avg_day[lower_idx].states[state_index] != None and avg_day[lower_idx-1].states[state_index] != None):
                            lower_idx = lower_idx - 1 # reduce the index to get the 2nd valid state
                            last_state = avg_day[lower_idx].states[state_index]
                        else:
                            lower_idx = lower_idx - 1

                    upper_idx = index + 1
                    while(next_state == None and upper_idx < len(avg_day)-2): # Find the next valid two states for that day
                        if(avg_day[upper_idx].states[state_index] != None and avg_day[upper_idx+1].states[state_index] != None):
                            upper_idx = upper_idx + 1
                            next_state = avg_day[upper_idx].states[state_index]
                        else:
                            upper_idx = upper_idx + 1
                    
                    #print(f"next: {next_state} last: {last_state} idx: {index}")
                    if(next_state != None and last_state != None): # If both states are present, linearly interpolate between them
                        n = upper_idx - lower_idx # Determine the linear interpolated values to fill the missing data
                        for i in range(lower_idx, upper_idx + 1):
                            avg_day[i].states[state_index] = last_state + (next_state - last_state) * ((i - lower_idx) / n)
                            #print(last_state + ((next_state - last_state) * (i - lower_idx)) / n)
                    elif(last_state != None):
                        avg_day[index].states[state_index] = avg_day[index-1].states[state_index] # Use just the last state if the next state isn't available
                    elif(next_state != None):
                        avg_day[index].states[state_index] = avg_day[index+1].states[state_index] # Use just the next state if the last state isn't available

            interval = avg_day[index] # Update the interval var with the latest data after cleaning
        
        for interval in avg_day:
            if(len(interval.states) == 0):
                raise Exception(f"Failed to get state data for {interval.time} time period")
            interval.state = round(sum(interval.states) / len(interval.states), 2)

            #print(f"avg: {interval.state} states: {interval.states}")

        #for i in range(len(avg_day)): # Print average for each day and each time
        #    print(avg_day[i].state)
        #    print(avg_day[i].states)       

        return avg_day

    def round_forecast_times(self, forecast_hours_from_now=None, forecast_till_time=None):
        rounded_current_time = self.round_minutes(datetime.datetime.now(), nearest_minute=5)
        if(forecast_hours_from_now):
            if(forecast_hours_from_now > 24):
                raise Exception(f"Unable to provide forecast more than 24hrs in the future. {forecast_hours_from_now} hrs requested")
            rounded_forecast_time = self.round_minutes(rounded_current_time + datetime.timedelta(hours=forecast_hours_from_now), nearest_minute=5).time()
        elif(forecast_till_time):
            rounded_forecast_time = self.round_minutes(forecast_till_time, nearest_minute=5)
        else:
            raise Exception("Must provide forecast hours or time to determine forecast!")
        
        rounded_current_time = rounded_current_time.time()

        return [rounded_current_time, rounded_forecast_time]
    
    def get_load_avg(self, days_ago, hours_update_interval=24): # hours_update_interval: frequency to update the load date
        if(time.time() - self.last_load_data_retrival_timestamp > hours_update_interval*60*60 or self.avg_load_day == None):
            self.avg_load_day = self.update_load_avg(days_ago)
            self.last_load_data_retrival_timestamp = time.time()
        return self.avg_load_day
    
    def forecast_load_power(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)

        avg_day_1_kwh = []
        avg_day_2_kwh = []
        for bin in avg_day:
            avg_day_1_kwh.append(StateClass(state=bin.state, states=[], time=bin.time))
            avg_day_2_kwh.append(StateClass(state=bin.state + avg_day[-1].state, states=[], time=bin.time))# Add the last kwh reading to the first to seemlesly transition to day 2


        avg_48hr_period_kwh = avg_day_1_kwh + avg_day_2_kwh

        #print(f"Avg1: {[round(a.state) for a in avg_day_1_kwh]}  \n\nAvg2: {[round(a.state) for a in avg_day_2_kwh]}")

        #print(f"Avg48: {[round(a.state,2) for a in avg_48hr_period_kwh[490:510]]}")

        start_idx = None
        end_idx = None
        for i in range(len(avg_48hr_period_kwh)):
            if(start_idx == None and avg_48hr_period_kwh[i].time == rounded_current_time):
                start_idx = i
            elif(start_idx != None and end_idx == None and avg_48hr_period_kwh[i].time == rounded_forecast_time):
                end_idx = i
                break
        
        #print(f"start: {start_idx}  stop: {end_idx}  total:{len(avg_48hr_period_kwh)}")

        forecast_power = []
        for i in range(start_idx, end_idx):
            if(i == 0):
                power = (avg_48hr_period_kwh[1].state - avg_48hr_period_kwh[0].state) / (5/60)
            else:
                power = (avg_48hr_period_kwh[i].state - avg_48hr_period_kwh[i-1].state) / (5/60)

            if(power <= 0):
                power = (avg_48hr_period_kwh[-1].state - avg_48hr_period_kwh[0].state)/48 #If we get a weird reading, replace it with the average

            forecast_power.append(StateClass(state=power, states=[], time=bin.time))
        
        return forecast_power
            
    def forecast_consumption_amount(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)
    
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
    
    def kwh_required_remaining(self, buffer_percentage=20):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(6, 0, 0))
        return max(forecast_kwh, 0) * (1 + (buffer_percentage/100)) + 2
        
    def round_minutes(self, time, nearest_minute):
        return time.replace(
            minute=(time.minute // nearest_minute) * nearest_minute,
            second=0,
            microsecond=0,
            tzinfo=HA_TZ
            )  
    
    # returns the forecast solar power for the requested time period in 5 minute increments
    def forecast_solar_power(self, forecast_hours_from_now):
        N_30min = forecast_hours_from_now * (60//30)
        N_5min = forecast_hours_from_now * (60//5)
        interpolation_steps = 30//5

        # Solar Forecast
        # Get solar forecast list from HA
        today = self.ha.get_state("sensor.solcast_pv_forecast_forecast_today")["attributes"]["detailedForecast"]
        tomorrow = self.ha.get_state("sensor.solcast_pv_forecast_forecast_tomorrow")["attributes"]["detailedForecast"]
        forecast = today + tomorrow # Combine

        df = pd.DataFrame(forecast) # Convert to DataFrame for easy time handling
        
        df["period_start"] = pd.to_datetime(df["period_start"]) # Parse timestamps (Solcast provides timezone-aware ISO strings)

        # Current time in same timezone
        now = pd.Timestamp.now(tz=df["period_start"].dt.tz)
        now = now.ceil("5min") #round to nearest 5 min

        # Keep only future (or current) periods
        df_future = (
            df[df["period_start"] >= now]
            .sort_values("period_start")
            .iloc[:N_5min]
        )

        # Solar forecast (kW)
        solar_30min = df_future["pv_estimate"].to_numpy()
        solar_30min = solar_30min[:N_30min]
        solar_5min = np.interp(
            np.arange(N_5min),
            np.arange(0, N_5min, interpolation_steps),
            solar_30min
        )
        solar_5min = solar_5min
        if len(solar_5min) < N_5min:
            raise RuntimeError(
                f"Solcast forecast too short: {len(solar_5min)} < {N_5min}"
            )
        
        return solar_5min[:N_5min] # return the solar forecast but limit the list length to the requested length

#from api_token_secrets import HA_URL, HA_TOKEN
#plant = Plant(HA_URL, HA_TOKEN, errors=True) 
#load = plant.forecast_load_power(forecast_hours_from_now=24)
#load = [round(load_state.state) for load_state in load]
#print(load)
