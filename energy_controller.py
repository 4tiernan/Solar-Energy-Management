class EnergyController():
    def __init__(self, ha, ha_mqtt, plant, kwh_required_remaining = 15, max_discharge_rate = 15, MINIMUM_BATTERY_DISPATCH_PRICE = 5, good_sell_price = 50):
        self.ha = ha
        self.ha_mqtt = ha_mqtt
        self.plant = plant

        self.target_dispatch_price = 0
        self.kwh_required_remaining = kwh_required_remaining
        self.max_discharge_rate = max_discharge_rate
        self.hrs_of_discharge_available = 2
        self.MINIMUM_BATTERY_DISPATCH_PRICE = ha_mqtt.min_dispatch_price_number.value, #minimum price that is worth dispatching the battery for
        self.good_sell_price = good_sell_price #price at which we want to run the battery almost flat to take advantage of

        self.last_control_mode = self.plant.get_plant_mode()

        #Self consume on startup for saftey if auto control on
        if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
            self.self_consumption()
                
    def dispatch(self):
        print("DISPATCHING !!!!!!!!!!!!!!!")
        self.ha_mqtt.working_mode_sensor.set_state("Dispatching")
        self.plant.set_control_limits(
            control_mode="Command Discharging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=0,
            pv=self.plant.max_pv_power,
            grid_export=self.plant.max_export_power,
            grid_import=0)

    def export_excess_solar(self):
        print("Exporting Excess Solar !!!!!!!!!!!!!")
        self.ha_mqtt.working_mode_sensor.set_state("Exporting Exccess Solar")
        self.plant.set_control_limits(
            control_mode="Maximum Self Consumption",
            discharge=self.plant.max_discharge_power,
            charge=self.plant.max_charge_power,
            pv=self.plant.max_pv_power,
            grid_export=self.plant.max_export_power,
            grid_import=0)


    def self_consumption(self):
        print("SELF CONSUMPTION !!!!!!!!!!!!!")
        self.ha_mqtt.working_mode_sensor.set_state("Self Consumption")
        self.plant.set_control_limits(
            control_mode="Maximum Self Consumption",
            discharge=self.plant.max_discharge_power,
            charge=self.plant.max_charge_power,
            pv=self.plant.max_pv_power,
            grid_export=0,
            grid_import=0)

    def run(self, amber_data):
        self.plant.update_data()
        feedIn_price = amber_data.feedIn_price

        self.target_dispatch_price = amber_data.feedIn_12hr_forecast_sorted[max(round(self.hrs_of_discharge_available*2 - 1),0)].price
        self.target_dispatch_price = round(max(self.target_dispatch_price, self.MINIMUM_BATTERY_DISPATCH_PRICE))

        #Plant.display_data()
        #print(f"Current General Price: {round(general_price)} c/kWh")
        print("...")
        print(f"kWh Drained: {round(self.plant.kwh_till_full, 2)} kWh")
        print(f"kWh Remaining: {round(self.plant.kwh_stored_available, 2)} kWh")
        print(f"Current FeedIn Price: {feedIn_price} c/kWh")
        print(f"Max Forecasted FeedIn Price: {amber_data.feedIn_max_forecast_price} c/kWh")
        print(f"Target Dispatch Price: {self.target_dispatch_price} c/kWh")

        good_price_conditions = feedIn_price >= self.good_sell_price and feedIn_price < 1000 and self.plant.kwh_stored_available > 5

        if(feedIn_price >= self.target_dispatch_price and self.plant.kwh_stored_available > self.kwh_required_remaining or good_price_conditions):
            self.dispatch()
            if(self.last_control_mode != self.plant.get_plant_mode()):
                self.last_control_mode = self.plant.get_plant_mode()
                self.ha.send_notification(f"Dispatching at {feedIn_price} c/kWh", f"kWh Drained: {self.plant.kwh_till_full} kWh", "mobile_app_pixel_10_pro")
            
        elif(feedIn_price < self.target_dispatch_price or self.plant.kwh_stored_available <= self.kwh_required_remaining):
            if(feedIn_price >= 0):
                self.export_excess_solar()
                if(self.last_control_mode != self.plant.get_plant_mode()):
                    self.last_control_mode = self.plant.get_plant_mode()
                    self.ha.send_notification(f"Exporting Excess Solar at {feedIn_price} c/kWh", f"kWh Drained: {self.plant.kwh_till_full} kWh", "mobile_app_pixel_10_pro")
            else:
                self.self_consumption()
                if(self.last_control_mode != self.plant.get_plant_mode()):
                    self.last_control_mode = self.plant.get_plant_mode()
                    self.ha.send_notification(f"Self Consuming at {feedIn_price} c/kWh", f"kWh Drained: {self.plant.kwh_till_full} kWh", "mobile_app_pixel_10_pro")
            
            
                