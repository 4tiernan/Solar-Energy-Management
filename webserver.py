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
def plot_mpc_results(output):
    """
    Plot MPC results using Plotly (dual-axis, 2 subplots)
    """

    # Convert time index
    try:
        time_index = [datetime.fromisoformat(t) for t in output["time_index"]]
    except Exception:
        time_index = list(range(len(output["battery_power"])))

    # -------------------------------
    # Figure with dual-axis support
    # -------------------------------
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        specs=[
            [{"secondary_y": True}],   # Power + Price
            [{"secondary_y": False}]   # SOC
        ]
    )

    # ===============================
    # TOP PLOT — POWER + PRICE
    # ===============================

    # ---- Power traces (LEFT axis)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["battery_power"],
        name="Battery Power (kW)",
        line=dict(color="blue")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["load"],
        name="Load",
        line=dict(color="orange")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["solar_forecast"],
        name="Available Solar",
        line=dict(color="limegreen", dash="dash")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["solar_used"],
        name="Solar Used",
        line=dict(color="limegreen")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["inverter_power"],
        name="Inverter Power",
        line=dict(color="purple")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["grid_net"],
        name="Grid Net (+buy / -sell)",
        line=dict(color="black", dash="dot")
    ), row=1, col=1, secondary_y=False)

    # ---- Price traces (RIGHT axis)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["prices_buy"],
        name="Buy Price ($/kWh)",
        line=dict(color="green")
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["prices_sell"],
        name="Sell Price ($/kWh)",
        line=dict(color="red")
    ), row=1, col=1, secondary_y=True)

    # Zero line
    fig.add_hline(y=0, row=1, col=1, line_width=1, line_color="black")

    # ===============================
    # BOTTOM PLOT — SOC
    # ===============================
    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["soc"][:-1],
        name="SOC (kWh)",
        line=dict(color="purple")
    ), row=2, col=1)

    fig.add_hline(
        y=output["soc_min"],
        line_dash="dash",
        line_color="red",
        annotation_text="SOC Min",
        row=2, col=1
    )

    fig.add_hline(
        y=output["soc_max"],
        line_dash="dash",
        line_color="red",
        annotation_text="SOC Max",
        row=2, col=1
    )

    fig.add_hline(
        y=output["low_energy_threshold"],
        line_dash="dash",
        line_color="orange",
        annotation_text="Low Energy",
        row=2, col=1
    )

    # ===============================
    # AXES / GRID / LIMITS
    # ===============================
    fig.update_yaxes(
        title_text="Power (kW)",
        range=[-15, 15],
        autorange=True,
        row=1, col=1, secondary_y=False
    )

    fig.update_yaxes(
        title_text="Price ($/kWh)",
        autorange=True,
        row=1, col=1, secondary_y=True
    )

    fig.update_yaxes(
        title_text="SOC (kWh)",
        range=[0, 40],
        autorange=True,
        row=2, col=1
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
        minor=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)"
        )
    )

    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
        minor=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)"
        )
    )

    # ===============================
    # LAYOUT
    # ===============================
    fig.update_layout(
        template="plotly_white",
        height=750,
        title="Battery Schedule & SOC (MPC)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    st.plotly_chart(fig, use_container_width=True)


plot_mpc_results(output)

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

