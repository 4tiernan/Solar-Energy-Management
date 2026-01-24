    def can_enter_mode(self, mode):
        if(mode == "Dispatching"):
            return (self.feedIn_price >= self.target_dispatch_price and
                     self.kwh_energy_available > self.kwh_required_remaining + 1)
        
        elif(mode == "Exporting All Solar"):
            return (self.solar_kwh_forecast_remaining + self.kwh_energy_available >= self.kwh_required_remaining + self.plant.kwh_till_full + 21 and
                     self.feedIn_price >= 2 and self.plant.solar_daytime)
        
        elif(mode == "Exporting Excess Solar"):
            return (self.feedIn_price < self.target_dispatch_price or self.kwh_energy_available <= self.kwh_required_remaining)
        
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
