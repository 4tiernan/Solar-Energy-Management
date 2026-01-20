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


st.subheader("🔋 MPC Plan Dashboard (Demo)")

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

import web_plot
web_plot.plot_mpc_results(st, output)

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

