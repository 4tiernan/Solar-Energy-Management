#pip install ecos
#pip install cvxpy numpy pandas
import numpy as np
import cvxpy as cp
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz
from amber_api import AmberAPI  # your AmberAPI code
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
from ha_api import HomeAssistantAPI

amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )

# -------------------------------
# Config
# -------------------------------
N = 24 * 2  # 12 hours, 30-min timesteps
dt = 0.5      # 30 minutes in hours

battery_capacity = 40.0  # kWh
soc_min = 0.1 * battery_capacity
soc_max = 1 * battery_capacity
p_max_charge = 15  # kW
p_max_discharge = 15  # kW
efficiency = 0.95
battery_discharge_cost = 0.08  # $/kWh

# -------------------------------
# Forecasts
# -------------------------------
# Example load and solar (replace with HA data)
load_30min = np.random.rand(int(N)) * 5       # kW
solar_30min = np.random.rand(int(N)) * 15     # kW

load_30min = np.full(int(N), 2.0)  # 3 kW constant load

solar_attributes = ha.get_state("sensor.solcast_pv_forecast_forecast_today")["attributes"]["detailedForecast"]
#solar_forecast = np.array([item["pv_estimate"] for item in solar_attributes])
#solar_30min = np.append(solar[38:], solar[:38]) # increments of 30 min forecast

# Get forecast list from HA
today = ha.get_state(
    "sensor.solcast_pv_forecast_forecast_today"
)["attributes"]["detailedForecast"]

tomorrow = ha.get_state(
    "sensor.solcast_pv_forecast_forecast_tomorrow"
)["attributes"]["detailedForecast"]

# Combine
forecast = today + tomorrow

# Convert to DataFrame for easy time handling
df = pd.DataFrame(forecast)

# Parse timestamps (Solcast provides timezone-aware ISO strings)
df["period_start"] = pd.to_datetime(df["period_start"])

# Current time in same timezone
now = pd.Timestamp.now(tz=df["period_start"].dt.tz)
now = now.ceil("30min") #round to nearest 30 min

# Keep only future (or current) periods
df_future = (
    df[df["period_start"] >= now]
    .sort_values("period_start")
    .iloc[:N]
)

# Solar forecast (kW)
solar_30min = df_future["pv_estimate"].to_numpy()

if len(solar_30min) < N:
    raise RuntimeError(
        f"Solcast forecast too short: {len(solar_30min)} < {N}"
    )


# -------------------------------
# Fetch Amber 12-hour forecast
# -------------------------------
# Replace with your actual API tokens and site ID
# amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)
# data = amber.get_data(partial_update=False)

# Use 12-hour general price forecast (30-min steps)
# general_prices = np.array([p.price for p in data.general_12hr_forecast])
# feedin_prices  = np.array([p.price for p in data.feedIn_12hr_forecast])

# For testing purposes, we simulate it
data = amber.get_data(partial_update=False)
[general_price_forecast, feed_in_price_forecast] = amber.get_forecast(next_intervals=48, resolution=30)

# Extract forecast prices
general_prices = np.array([pf.price for pf in general_price_forecast])       # buy price
feedin_prices  = np.array([pf.price for pf in feed_in_price_forecast])       # sell price

# Ensure we only take the next 12 hours (24 steps for 30-min intervals)
general_prices = general_prices[:N]
feedin_prices  = feedin_prices[:N]

# Assign to optimization variables
prices_buy  = general_prices
prices_sell = feedin_prices

# -------------------------------
# Variables
# -------------------------------
p_charge = cp.Variable(int(N), nonneg=True)
p_discharge = cp.Variable(int(N), nonneg=True)
soc = cp.Variable(int(N)+1)

# Grid import/export split
grid_import = cp.Variable(int(N), nonneg=True)
grid_export = cp.Variable(int(N), nonneg=True)

# -------------------------------
# Constraints
# -------------------------------
constraints = []
soc_init = 1 * battery_capacity
constraints += [soc[0] == soc_init]

for t in range(int(N)):
    # SoC dynamics
    constraints += [soc[t+1] == soc[t] + dt * efficiency * p_charge[t] - dt / efficiency * p_discharge[t]]
    
    # Power limits
    constraints += [p_charge[t] <= p_max_charge]
    constraints += [p_discharge[t] <= p_max_discharge]
    
    # SoC limits
    constraints += [soc[t+1] >= soc_min, soc[t+1] <= soc_max]
    
    # Grid import/export relation
    net_grid = load_30min[t] - solar_30min[t] + p_charge[t] - p_discharge[t]
    constraints += [grid_import[t] - grid_export[t] == net_grid]
    constraints += [grid_import[t] >= 0, grid_export[t] >= 0]

# -------------------------------
# Objective: Minimise cost including battery discharge cost
# -------------------------------
objective = cp.Minimize(
    cp.sum(cp.multiply(grid_import, prices_buy) * dt
           - cp.multiply(grid_export, prices_sell) * dt
           + battery_discharge_cost * p_discharge * dt)
)

# -------------------------------
# Solve
# -------------------------------
prob = cp.Problem(objective, constraints)
prob.solve(solver=cp.ECOS)

# -------------------------------
# Results
# -------------------------------
battery_power = p_charge.value - p_discharge.value
grid_net = grid_import.value - grid_export.value
hours = np.arange(int(N)) * dt

plt.figure(figsize=(14,8))

# --------- Top plot: battery & net load ----------
plt.subplot(2,1,1)
plt.plot(hours, battery_power, label='Battery Power (kW)', color='blue')
plt.plot(hours, load_30min, label='Load', color='orange', alpha=0.6)
plt.plot(hours, solar_30min, label='Solar', color='yellow', alpha=1)
plt.plot(hours, grid_net, label='Grid Net Import (+ buy, - sell)', color='black', linestyle='--')
plt.axhline(0, color='black', linewidth=0.5)
plt.ylabel('Power (kW)')
plt.title('Battery Schedule & Net Load with 12h Amber Forecast and Discharge Cost')
plt.legend()
plt.grid(True)

# Secondary y-axis for prices
plt.twinx()
plt.plot(hours, prices_buy, label='Buy Price', color='green')
plt.plot(hours, prices_sell, label='Sell Price', color='red')
plt.ylabel('Price ($/kWh)')
plt.legend(loc='upper right')

# --------- Bottom plot: SOC ----------
plt.subplot(2,1,2)
plt.plot(hours.tolist() + [hours[-1]+dt], soc.value, label='Battery SOC (kWh)', color='purple')
plt.axhline(soc_min, color='red', linestyle='--', label='SOC Min/Max')
plt.axhline(soc_max, color='red', linestyle='--')
plt.xlabel('Hour of Day')
plt.ylabel('SOC (kWh)')
plt.title('Battery State of Charge')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()
