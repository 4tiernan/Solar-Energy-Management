class EnergyController():
    def __init__(self, ha, ha_mqtt, plant, buffer_percentage_remaining, max_discharge_rate = 15, MINIMUM_BATTERY_DISPATCH_PRICE = 10):
        self.ha = ha
        self.ha_mqtt = ha_mqtt
        self.plant = plant

        self.MODES = [
            "Dispatching",
            "Exporting All Solar",
            "Exporting Excess Solar",
            "Self Consumption"
        ]

        self.feedIn_price = 0
        self.target_dispatch_price = 0
        self.buffer_percentage_remaining = buffer_percentage_remaining
        self.solar_kwh_forecast_remaining = 0
        self.kwh_energy_available = 0 # kWh of battery and solar available to use today
        self.kwh_required_remaining = self.plant.kwh_required_remaining(buffer_percentage=self.buffer_percentage_remaining)
        self.max_discharge_rate = max_discharge_rate
        self.hrs_of_discharge_available = 2
        self.MINIMUM_BATTERY_DISPATCH_PRICE = ha_mqtt.min_dispatch_price_number.value #minimum price that is worth dispatching the battery for
        self.working_mode = "Self Consumption"
        self.target_price_reduction_percentage = 10 # Percentage reduction of ideal sell price to sell at (Assumes the max price won't occour)

        self.last_control_mode = self.plant.get_plant_mode()

        #Self consume on startup for saftey if auto control on
        if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
            self.self_consumption()
                
    def dispatch(self):
        self.working_mode = "Dispatching"
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Command Discharging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=0,
            pv=self.plant.max_pv_power,
            grid_export=self.plant.max_export_power,
            grid_import=0)
        
    def export_all_solar(self):
        self.working_mode = "Exporting All Solar"

        solar_buffer = 2 # Buffer to ensure load is covered by battery or solar
        if(self.plant.load_power + solar_buffer < self.plant.solar_kw): # Let the battery charge with excess DC power available
            self.plant.check_control_limits(
                working_mode=self.working_mode,
                control_mode="Command Discharging (PV First)",
                discharge=0,
                charge=self.plant.max_charge_power,
                pv=self.plant.max_pv_power,
                grid_export=self.plant.max_export_power,
                grid_import=0)
        else: # Make sure the battery supplies the load if solar power is minimal
            self.plant.check_control_limits(
                working_mode=self.working_mode,
                control_mode="Command Charging (PV First)",
                discharge=self.plant.max_discharge_power,
                charge=0,
                pv=self.plant.max_pv_power,
                grid_export=self.plant.max_export_power,
                grid_import=0)

    def export_excess_solar(self):
        self.working_mode = "Exporting Excess Solar"
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Maximum Self Consumption",
            discharge=self.plant.max_discharge_power,
            charge=self.plant.max_charge_power,
            pv=self.plant.max_pv_power,
            grid_export=self.plant.max_export_power,
            grid_import=0)


    def self_consumption(self):
        self.working_mode = "Self Consumption"
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Maximum Self Consumption",
            discharge=self.plant.max_discharge_power,
            charge=self.plant.max_charge_power,
            pv=self.plant.max_pv_power,
            grid_export=0,
            grid_import=0)
        
    def update_values(self, amber_data):
        self.plant.update_data()
        self.feedIn_price = amber_data.feedIn_price
        self.solar_kwh_forecast_remaining = self.ha.get_numeric_state("sensor.solcast_pv_forecast_forecast_remaining_today")
        self.kwh_required_remaining = self.plant.kwh_required_remaining(buffer_percentage=self.buffer_percentage_remaining)

        self.kwh_energy_available = self.plant.kwh_stored_available
        
        self.hrs_of_discharge_available = max((self.kwh_energy_available - self.kwh_required_remaining) / self.plant.max_export_power, 0) #constrain to not go negative

        self.target_dispatch_price = amber_data.feedIn_12hr_forecast_sorted[max(round(self.hrs_of_discharge_available*2),0)].price # get the number of 30 minute periods that the battery is allowed to discharge to
        self.target_dispatch_price = ((100-self.target_price_reduction_percentage)/100.0) * self.target_dispatch_price # Slightly reduce the target dispatch price to capture more events that are still valuable given forecast uncertanty 
        self.target_dispatch_price = round(max(self.target_dispatch_price, self.MINIMUM_BATTERY_DISPATCH_PRICE)) 
        #print(f"Discharge 30 minute windows: {self.hrs_of_discharge_available*2}")
        

    def print_values(self, amber_data):
        print("...")
        print(f"kWh Drained: {round(self.plant.kwh_till_full, 2)} kWh")
        print(f"kWh Energy Available: {round(self.kwh_energy_available, 2)} kWh")
        print(f"Current FeedIn Price: {self.feedIn_price} c/kWh")
        print(f"Max Forecasted FeedIn Price: {amber_data.feedIn_max_forecast_price} c/kWh")
        print(f"Target Dispatch Price: {self.target_dispatch_price} c/kWh")

    def can_enter_mode(self, mode):
        if(mode == "Dispatching"):
            return (self.feedIn_price >= self.target_dispatch_price and
                     self.kwh_energy_available > self.kwh_required_remaining + 1)
        
        elif(mode == "Exporting All Solar"):
            return (self.solar_kwh_forecast_remaining + self.kwh_energy_available >= self.kwh_required_remaining + self.plant.kwh_till_full + 21 and
                     self.feedIn_price >= 2 and self.plant.solar_daytime)
        
        elif(mode == "Exporting Excess Solar"):
            return (self.feedIn_price >= 0)
        
        elif(mode == "Self Consumption"):
            return True
        
        else:
            raise(f"Error, mode '{mode}' is unknown")
        
    def should_exit(self, mode):
        if(mode == "Dispatching"):
            return (self.feedIn_price < self.target_dispatch_price or
                     self.kwh_energy_available <= self.kwh_required_remaining)
        
        elif(mode == "Exporting All Solar"):
            return (self.solar_kwh_forecast_remaining + self.kwh_energy_available < self.kwh_required_remaining + self.plant.kwh_till_full + 20 or
                     self.feedIn_price < 2 or not self.plant.solar_daytime)
        
        elif(mode == "Exporting Excess Solar"):
            return (self.feedIn_price < 0)
        
        elif(mode == "Self Consumption"): # No need to exit lowest mode unless another mode can be active
            return False
            
        else:
            raise(f"Error, mode '{mode}' is unknown")
        
    def select_mode(self):
        current_mode = self.working_mode

        # Check for higher priority modes that can be selected
        for mode in self.MODES:
            if current_mode is None or self.MODES.index(mode) <  self.MODES.index(current_mode):
                if(self.can_enter_mode(mode)):
                    return mode

        # Check current control mode still wants control
        if current_mode and not self.should_exit(current_mode):
            return current_mode
        
        # Fall back to best available mode
        for mode in self.MODES:
            if self.can_enter_mode(mode):
                return mode
        
        return None

    def run(self, amber_data):
        self.update_values(amber_data=amber_data)

        #Plant.display_data()
        #print(f"Current General Price: {round(general_price)} c/kWh")

        last_working_mode = self.working_mode
        self.working_mode = self.select_mode()

        if(last_working_mode != self.working_mode):
            self.print_values(amber_data)

        self.mainain_control_mode()

    def mainain_control_mode(self):
        self.plant.update_data()
        if(self.working_mode == "Self Consumption"):
            self.self_consumption()
        elif(self.working_mode == "Exporting Excess Solar"):  
            self.export_excess_solar()        
        elif(self.working_mode == "Exporting All Solar"):
            self.export_all_solar()
        elif(self.working_mode == "Dispatching"):
            self.dispatch()
        else:
            self.self_consumption()
            raise(f"Error, control mode {self.working_mode} not defined. Defaulting to self consumption.")
            
                