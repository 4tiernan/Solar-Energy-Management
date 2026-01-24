class EnergyController():
    def __init__(self, ha, ha_mqtt, plant, rbc):
        self.ha = ha
        self.ha_mqtt = ha_mqtt
        self.plant = plant
        self.rbc = rbc

        self.MODES = [
            "Dispatching",
            "Exporting All Solar",
            "Exporting Excess Solar",
            "Self Consumption"
        ]
        
        self.working_mode = "Self Consumption"

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

    def run(self, amber_data):
        last_working_mode = self.working_mode
        self.working_mode = self.rbc.run(amber_data)

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
            
                