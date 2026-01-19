import streamlit as st
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import paho.mqtt.client as mqtt
from api_token_secrets import MQTT_HOST, MQTT_USER, MQTT_PASS
import datetime
import time

if "mpc_output" not in st.session_state:
    st.session_state.mpc_output = {}

output = {
    "time_index": [0,1,2,3],
    "battery_power": [0,1,2,3],
    "soc": [0,1,2,3],
    "grid_net": [0,1,2,3],
    "prices_buy": [0,1,2,3],
    "prices_sell": [0,1,2,3],
    "profit": 0,
    "inverter_power": [0,1,2,3],
    "solar_forecast": [0,1,2,3],
    "solar_used": [0,1,2,3],
    "load": [0,1,2,3]
}

data_received = False

def on_message(client, userdata, msg):
    global output, data_received
    output = json.loads(msg.payload)
    data_received = True

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_message = on_message
client.connect(MQTT_HOST, 1883)
client.subscribe("home/mpc/output")
client.loop_start()

# Wait until we get data before trying to display it
while data_received == False:
    time.sleep(0.01)

st.set_page_config(
    page_title="MPC Dashboard",
    layout="wide"
)


st.title("🔋 MPC Plan Dashboard (Demo)")

# -----------------------------
# Sidebar controls (MPC params)
# -----------------------------
with st.sidebar:
    st.header("MPC Parameters")

    horizon = st.slider("Horizon (steps)", 6, 48, 24)
    soc_init = st.slider("Initial SOC (%)", 0.0, 100.0, 50.0)
    soc_target = st.slider("Target SOC (%)", 0.0, 100.0, 80.0)

    p_max = st.slider("Max charge power (kW)", 1.0, 10.0, 5.0)
    dt = st.number_input("Timestep (hours)", value=0.5)


# -----------------------------
# Convert time strings to datetime objects
# -----------------------------
try:
    time_index = [datetime.fromisoformat(t) for t in output["time_index"]]
except Exception:
    time_index = list(range(len(output["soc"])))

# -----------------------------
# Plot: SOC trajectory (functional)
# -----------------------------
def display_results_streamlit(output):
    st.write(f"Profit: ${round(output['profit'], 2)}")
    st.write(
        f"solar used: {round(output['solar_used'][0],2)}  "
        f"bat: {round(output['battery_power'][0],2)}  "
        f"load: {round(output['load'][0],2)}  "
        f"grid: {round(output['grid_net'][0],2)}  "
        f"inverter_power: {round(output['inverter_power'][0], 2)}"
    )

    # Create 2-row subplot (power + SOC)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        subplot_titles=("Battery Schedule & Net Load", "Battery State of Charge"),
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
    )

    # --------- Top plot: battery & net load ----------
    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["battery_power"],
        name='Battery Power (kW)'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["load"],
        name='Load'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["solar_forecast"],
        name='Available Solar', line=dict(dash='dash')
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["solar_used"],
        name='Solar Used'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["inverter_power"],
        name='Inverter Power (kW)'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["grid_net"],
        name='Grid Net Import (+ buy, - sell)', line=dict(dash='dash')
    ), row=1, col=1)

    # Secondary y-axis for prices (same subplot)
    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["prices_buy"],
        name='Buy Price'
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["prices_sell"],
        name='Sell Price'
    ), row=1, col=1, secondary_y=True)

    # Add 0 line
    fig.add_hline(y=0, line=dict(color='black', width=1), row=1, col=1)

    # --------- Bottom plot: SOC ----------
    fig.add_trace(go.Scatter(
        x=output["time_index"], y=output["soc"][:-1],
        name='Battery SOC (kWh)'
    ), row=2, col=1)

    #fig.add_hline(y=self.soc_min, line=dict(color='red', dash='dash'), row=2, col=1)
    #fig.add_hline(y=self.soc_max, line=dict(color='red', dash='dash'), row=2, col=1)
    #fig.add_hline(y=self.battery_low_energy_threshold, line=dict(color='orange', dash='dash'), row=2, col=1)

    # Layout
    fig.update_layout(height=800, showlegend=True)
    fig.update_xaxes(title_text="Hour of Day", row=2, col=1)

    # ---- set soft limits for SOC ----
    fig.update_yaxes(range=[0, 45], constrain='range', row=2, col=1)

    # ---- set soft limits for schedule ----
    fig.update_yaxes(range=[-16, 16], constrain='range', row=1, col=1)

    # Grid lines
    fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor="LightGray")
    fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor="LightGray")

    st.plotly_chart(fig, use_container_width=True)


display_results_streamlit(output)

# -----------------------------
# Layout
# -----------------------------
#col1, col2 = st.columns(2)

#with col1:
#    st.plotly_chart(soc_fig, use_container_width=True)

#with col2:
#    st.plotly_chart(power_fig, use_container_width=True)
# -----------------------------
# Debug / inspection
# -----------------------------
#with st.expander("Raw MPC Output"):
#    st.write("SOC:", soc)
#    st.write("Power:", power)

