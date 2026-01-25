#pip install ecos
#pip install cvxpy numpy pandas
import numpy as np
import cvxpy as cp
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz
import matplotlib.dates as mdates
import time
from energy_controller import ControlMode

class MPC:
    def __init__(self, ha, plant, EC):
        self.plant = plant
        self.ha = ha
        self.EC = EC

        self.power_threshold = 0.2 # Threshold when comparing power values

        self.update_limits()    # Update fixed limits (some are required for config)

        # ---------- Config ----------
        self.forecast_hrs = 24
        self.steps_per_price = 30 // 5  # = 6
        self.steps_per_hr = 60 // 5

        self.N_30min = self.forecast_hrs * (60 // 30) # forecast hours, 5-min timesteps
        self.N_5min = self.forecast_hrs * (60 // 5)
        self.amber_forecast_30min_intervals = (60//30)*12    # Get the max 12hr forecast
        self.amber_past_30min_intervals = self.N_30min - self.amber_forecast_30min_intervals  # Fill the rest of the sim with past prices
        self.amber_5min_intervals = (60//5)*12

        self.dt_5min = 5/60      # 5 minutes in hours

        # Battery Settings
        self.soc_min = 0.0 * self.battery_capacity
        self.soc_max = 1.0 * self.battery_capacity
        self.discharge_efficiency = 0.95
        self.battery_min_export_cost = 0.07  # $/kWh (Export will only occour ABOVE this value)
        self.grid_import_penalty_cost = 0.10 # $/kWh penalty for using grid power
        self.battery_low_energy_threshold = 5 # kWh
        self.battery_low_energy_penalty_cost = 0.01 # $/kWh 0.03-0.05 is ok
        self.solar_curtailment_penalty = 0.0001  # $/kWh just enough to encorage use of the solar
       
    def update_limits(self):
        self.battery_capacity = self.plant.rated_capacity  # kWh
        self.solar_dc_max = self.plant.max_pv_power             # kW (DC limit for MPPTs)
        self.p_max_charge = self.plant.max_charge_power         # kW (Battery max charge rate)
        self.p_max_discharge = self.plant.max_discharge_power   # kW (Battery max discharge rate)
        self.inverter_p_max = self.plant.max_inverter_power     # kW (Inverter power limit)
        self.grid_import_limit = self.plant.max_import_power    # kW (Grid import limit)
        self.grid_export_limit = self.plant.max_export_power    # kW (Grid export limit)      

    # Update any values or forecasts required to run the sim
    def update_values(self, amber_data, inject_real_values = True):        
        self.soc_init = self.plant.kwh_stored_available

        # ---------- Forecasts ----------
        # Load Forecast
        load_power_states = self.plant.forecast_load_power(forecast_hours_from_now=self.forecast_hrs) # Calculate the average load power
        self.load_5min = [powerstate.state for powerstate in load_power_states]
        
        # Solar Forecast
        self.solar_5min = self.plant.forecast_solar_power(forecast_hours_from_now=self.forecast_hrs)

        # Inject the current real load and solar values into the sim
        if(inject_real_values):
            self.plant.update_data()
            self.solar_5min[0] = self.plant.solar_kw
            self.load_5min[0] = self.plant.load_power

        # Amber Forecast (forecast hrs is set in main.py in the get_data call)
        general_price_forecast = amber_data.general_extrapolated_forecast
        feed_in_price_forecast = amber_data.feedIn_extrapolated_forecast

        # Convert to $/kWh
        self.prices_buy = np.array(general_price_forecast) / 100      # buy price in $ from cents
        self.prices_sell  = np.array(feed_in_price_forecast) / 100      # sell price in $ from cents

    def run_optimisation(self, amber_data):
        self.update_values(amber_data)

        self.prices_sell = self.prices_sell - 0.0001 # Not sure what this is for

        start = time.time()
        # ----------- Variables -----------
        # Battery
        p_charge = cp.Variable(int(self.N_5min), nonneg=True)
        p_discharge = cp.Variable(int(self.N_5min), nonneg=True)
        soc = cp.Variable(int(self.N_5min)+1)
        low_energy_violation = cp.Variable(int(self.N_5min), nonneg=True)

        # Solar
        solar_used = cp.Variable(int(self.N_5min), nonneg=True) # Solar used out of the forecast value (allows for curtailment)
        solar_curtail = cp.Variable(int(self.N_5min), nonneg=True) # Approximate amount of curtailment occouring


        # Grid import/export
        grid_import = cp.Variable(int(self.N_5min), nonneg=True)
        grid_export = cp.Variable(int(self.N_5min), nonneg=True)

        # Inverter
        inverter_power = cp.Variable(int(self.N_5min), nonneg=False) # Discharge to grid is positive

        # ----------- Constraints -----------
        constraints = []
        constraints += [soc[0] == self.soc_init] # Set the inital soc 
        constraints += [soc[-1] == min(self.soc_max*0.99, self.soc_init)] # Set the final soc to be close to the starting soc but limit to ensure possibility

        #self.prices_sell[250:270] = -0.30 # Allow testing of various pricings
        #self.prices_buy[250:270] = -0.20

        #self.prices_sell[100:150] = 0.50 # Allow testing of various pricings
        #self.prices_buy[100:150] = 0.70

        #zero_price_mask = (self.prices_sell == 0).astype(float) # Represents when prices are zero

        #low_price_mask = (self.prices_sell < self.battery_min_export_cost).astype(float) # Mask to represent when price is below min dispatch price
        #battery_export = cp.Variable(int(self.N_5min), nonneg=True)

        for t in range(int(self.N_5min)):
            # SoC dynamics
            constraints += [soc[t+1] == soc[t] + self.dt_5min * self.discharge_efficiency * p_charge[t] 
                            - self.dt_5min / self.discharge_efficiency * p_discharge[t]]
            # SoC limits
            constraints += [soc[t+1] >= self.soc_min, soc[t+1] <= self.soc_max]
            constraints += [soc[t+1] + low_energy_violation[t] >= self.battery_low_energy_threshold] # Soft reserve 

            # Battery Power limits
            constraints += [p_charge[t] <= self.p_max_charge]
            constraints += [p_discharge[t] <= self.p_max_discharge]
            
            # Limit battery discharge export based on price
            #if(self.prices_sell[t] < self.battery_min_export_cost):
            #    constraints += [(p_discharge[t] <= max(0, self.load_5min[t] - self.solar_5min[t]))]

            # DC Solar Limits
            constraints += [solar_used[t] <= self.solar_5min[t],    # Solar cannot exceed forecast
                            solar_used[t] <= self.solar_dc_max,     # DC MPPT Limit
                            solar_used[t] + solar_curtail[t] == self.solar_5min[t] # Solar Curtailment
                            ]     
            
            # DC Balance, Sum Inputs == Sum Outputs to DC bus
            constraints += [solar_used[t] + p_discharge[t] == p_charge[t] + inverter_power[t]]

            # AC Power Balance, Sum AC Sources == Sum AC Sinks
            constraints += [grid_import[t] + inverter_power[t] == self.load_5min[t] + grid_export[t]]

            constraints += [grid_import[t] <= self.grid_import_limit,
                            grid_export[t] <= self.grid_export_limit]

            # Inverter AC Limit
            constraints += [inverter_power[t] <= self.inverter_p_max,
                            inverter_power[t] >= -self.inverter_p_max]

        # -------------------------------
        # Objective: Minimise cost including battery discharge cost
        # -------------------------------
        objective = cp.Minimize(
            cp.sum(cp.multiply(grid_import, self.prices_buy) * self.dt_5min
                - cp.multiply(grid_export, self.prices_sell) * self.dt_5min
                + cp.multiply(grid_import, self.grid_import_penalty_cost) * self.dt_5min
                + cp.multiply(self.battery_low_energy_penalty_cost,  low_energy_violation) * self.dt_5min
                + cp.multiply(self.solar_curtailment_penalty, solar_curtail) * self.dt_5min
                + cp.multiply(self.battery_min_export_cost, p_discharge) * self.dt_5min
                ))
        
        #  self.charge_reward = 0.00
        # - cp.multiply(self.charge_reward, p_charge) * self.dt_5min
        # + battery_discharge_cost * p_discharge * dt
        # + battery_export_cost * (grid_export - solar_5min) * dt
        # + cp.multiply(battery_export, low_price_mask * self.battery_min_export_cost) * self.dt_5min

        # ---------- Solve ----------
        prob = cp.Problem(objective, constraints)
        prob.solve(solver=cp.ECOS)
        print(f"Solver took {round(time.time()-start,2)} seconds to solve")

        # Don't continue if the solver failed
        if prob.status not in ("optimal", "optimal_inaccurate"):
            raise RuntimeError(f"MPC solve failed: {prob.status}")
        
        else: # Sim successfull 
            # ---------- Results ----------
            battery_power = (p_discharge.value - p_charge.value).tolist()
            grid_net = (grid_import.value - grid_export.value).tolist()
            #hours = np.arange(int(self.N_5min)) * self.dt_5min

            now = datetime.now().replace(second=0, microsecond=0)
            time_index = [now + timedelta(minutes=5 * i) for i in range(int(self.N_5min))]

            grid_kwh_import_per_interval = grid_import.value / self.steps_per_hr 
            grid_kwh_export_per_interval = grid_export.value / self.steps_per_hr 

            cost_import = np.sum(grid_kwh_import_per_interval * self.prices_buy)   # $ paid to grid
            revenue_export = np.sum(grid_kwh_export_per_interval * self.prices_sell)  # $ earned from export
            grid_profit = revenue_export - cost_import

            # store it in shared dict
            output = {
                "time_index": [time_idx.isoformat() for time_idx in time_index],
                "battery_power": battery_power,
                "soc": soc.value.tolist(),
                "grid_net": grid_net,
                "prices_buy": self.prices_buy.tolist(),
                "prices_sell": self.prices_sell.tolist(),
                "profit": float(grid_profit),
                "inverter_power": inverter_power.value.tolist(),
                "solar_forecast": self.solar_5min,
                "solar_used": solar_used.value.tolist(),
                "load": self.load_5min,
                "soc_min": self.soc_min,
                "soc_max": self.soc_max,
                "low_energy_threshold": self.battery_low_energy_threshold
            }
            
            return self.convert_to_python(output)
        
    def convert_to_python(self, obj): # Convert all np objects to python objects
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: self.convert_to_python(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.convert_to_python(v) for v in obj]
        return obj
    
    def determine_control_mode(self, output):
        inverter_power = output["inverter_power"][0]
        solar_power = output["solar_used"][0]
        solar_forecast = output["solar_forecast"][0]
        load_power = output["load"][0]
        grid_net = output["grid_net"][0]
        battery_power = output["battery_power"][0]

        if(approx_equal(inverter_power, solar_power) or (approx_equal(inverter_power, self.plant.max_inverter_power) and solar_power > self.plant.max_inverter_power)):
            self.EC.export_all_solar() # Export if all solar is being exported or > max inverter and charging bat with excess
        
        elif(approx_equal(inverter_power, load_power)):
            if(battery_power < self.power_threshold): # If the battery is charging
                return self.EC.self_consumption()
            else:  
                return self.EC.solar_to_load() # If battery is not charging, send solar straight to load
        
        elif(inverter_power > solar_power + self.power_threshold and inverter_power > load_power + self.power_threshold):
            return self.EC.dispatch(grid_export_limit = abs(grid_net))
        
        elif(grid_net < -self.power_threshold and solar_power > inverter_power + self.power_threshold):
            return self.EC.export_excess_solar(grid_export_limit = abs(grid_net))
        
        elif(approx_equal(grid_net, load_power)):
            return self.EC.import_power(battery_charge_limit = 0)
        
        elif(inverter_power < 0 and battery_power < self.power_threshold):
            return self.EC.import_power(battery_charge_limit = abs(battery_power), pv_limit = solar_power)

        else:
            self.EC.self_consumption()
            raise Exception("Unable to determine control mode from MPC plan. Selected self consumption for saftey")

    def run(self, amber_data):
        output = self.run_optimisation(self, amber_data)
        control_mode = self.determine_control_mode(output)
        return output, control_mode

    def display_results(self, output):
        print(f"Profit: ${round(output['profit'], 2)}")
        #print(f"Solar Remaining {np.sum(solar_5min*(5/60))}")
        print(f"solar used: {round(output['solar_used'][0],2)}  bat: {round(output['battery_power'][0],2)}  load: {round(output['load'][0],2)} grid: {round(output['grid_net'][0],2)}  inverter_power: {round(output['inverter_power'][0], 2)}")

        plt.figure(figsize=(14,8))

        time_index = output["time_index"]
        # --------- Top plot: battery & net load ----------
        plt.subplot(2,1,1)
        plt.plot(time_index, output["battery_power"], label='Battery Power (kW)', color='blue')
        plt.plot(time_index, output["load"], label='Load', color='orange', alpha=1)
        plt.plot(time_index, output["solar_forecast"], label='Available Solar', color='limegreen', alpha=1, linestyle='--')
        plt.plot(time_index, output["solar_used"], label='Solar Used', color='limegreen')
        plt.plot(time_index, output["inverter_power"], label='Inverter Power (kW)', color='purple')
        plt.plot(time_index, output["grid_net"], label='Grid Net Import (+ buy, - sell)', color='black', linestyle='--')
        plt.axhline(0, color='black', linewidth=0.5)
        plt.ylabel('Power (kW)')
        plt.title('Battery Schedule & Net Load with 24h Amber Forecast and Discharge Cost')
        plt.legend()
        plt.grid(True)

        # Secondary y-axis for prices
        plt.twinx()
        plt.plot(time_index, output["prices_buy"], label='Buy Price', color='green')
        plt.plot(time_index, output["prices_sell"], label='Sell Price', color='red')
        plt.ylabel('Price ($/kWh)')
        plt.legend(loc='upper right')

        # --------- Bottom plot: SOC ----------
        plt.subplot(2,1,2)
        plt.plot(time_index, output["soc"][0:-1], label='Battery SOC (kWh)', color='purple')
        plt.axhline(self.soc_min, color='red', linestyle='--', label='SOC Min/Max')
        plt.axhline(self.soc_max, color='red', linestyle='--')
        plt.axhline(self.battery_low_energy_threshold, color='orange', linestyle='--', label='Low Energy Threshold')

        plt.xlabel('Hour of Day')
        plt.ylabel('SOC (kWh)')
        plt.title('Battery State of Charge')
        plt.legend()
        plt.grid(True)

        for ax in plt.gcf().axes:
            ax.xaxis.set_major_locator(mdates.HourLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.tick_params(axis='x', rotation=0)

        plt.tight_layout()
        plt.show()

def approx_equal(a, b, threshold = 0.2):
    return abs(a-b) < threshold

from amber_api import AmberAPI  
from ha_api import HomeAssistantAPI
import ha_mqtt
from energy_controller import EnergyController
import PlantControl
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
from RBC import RBC


amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 
ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )
rbc = RBC(
    ha=ha, 
    ha_mqtt=ha_mqtt,
    plant=plant, 
    buffer_percentage_remaining=35, # percentage to inflate predicted load consumption
)
EC = EnergyController(
    ha=ha,
    ha_mqtt=ha_mqtt, 
    plant=plant,
    rbc=rbc
)

mpc = MPC(ha, plant, EC)

amber_data = amber.get_data(forecast_hrs=mpc.forecast_hrs)

output = mpc.run_optimisation(amber_data)
mpc.determine_control_mode(output)
#mpc.display_results(output)
