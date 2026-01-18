import streamlit as st
import numpy as np
import plotly.graph_objects as go

st.set_page_config(
    page_title="MPC Dashboard",
    layout="wide"
)

data = {
    "time_index": [0,1,2,3],
    "soc": [0,2,4,6]
}

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
# Plot: SOC trajectory
# -----------------------------
soc_fig = go.Figure()
soc_fig.add_trace(go.Scatter(
    x=data["time_index"],
    y=data["soc"],
    mode="lines+markers",
    name="SOC (%)"
))
soc_fig.add_hline(
    y=soc_target,
    line_dash="dash",
    annotation_text="Target SOC"
)

soc_fig.update_layout(
    title="SOC Plan",
    xaxis_title="Time (hours)",
    yaxis_title="SOC (%)",
    height=350
)

# -----------------------------
# Plot: Power plan
# -----------------------------
#p_fig = go.Figure()
#p_fig.add_trace(go.Bar(
#    x=time[:-1],
#    y=power,
#    name="Battery Power (kW)"
#))

#p_fig.update_layout(
#    title="Battery Power Plan",
#    xaxis_title="Time (hours)",
#    yaxis_title="Power (kW)",
#    height=350
#)

# -----------------------------
# Layout
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    st.plotly_chart(soc_fig, use_container_width=True)

#with col2:
#    st.plotly_chart(p_fig, use_container_width=True)

# -----------------------------
# Debug / inspection
# -----------------------------
#with st.expander("Raw MPC Output"):
#    st.write("SOC:", soc)
#    st.write("Power:", power)
