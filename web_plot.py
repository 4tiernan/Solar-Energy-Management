import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime

# -----------------------------
# Plot: SOC trajectory (functional)
# -----------------------------
def plot_mpc_results(st, output):
    """
    Plot MPC results using Plotly (dual-axis, 2 subplots)
    Expects soc_min, soc_max, low_energy_threshold in output dict
    """

    # -------------------------------
    # Extract limits safely
    # -------------------------------
    soc_min = output.get("soc_min", None)
    soc_max = output.get("soc_max", None)
    low_energy_threshold = output.get("low_energy_threshold", None)

    # -------------------------------
    # Time index handling
    # -------------------------------
    try:
        time_index = [datetime.fromisoformat(t) for t in output["time_index"]]
    except Exception:
        time_index = list(range(len(output["battery_power"])))

    # -------------------------------
    # Create figure
    # -------------------------------
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.65, 0.35],  # Row height proportions
        specs=[
            [{"secondary_y": True}],   # Power + Price
            [{}]                       # SOC
        ]
    )

    # ===============================
    # TOP: POWER + PRICE
    # ===============================

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

    # Prices (right axis)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100) for v in output["prices_buy"]],
        name="Buy Price (c/kWh)",
        line=dict(color="green")
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100) for v in output["prices_sell"]],
        name="Sell Price (c/kWh)",
        line=dict(color="red")
    ), row=1, col=1, secondary_y=True)

    fig.add_hline(y=0, row=1, col=1, line_color="black", line_width=1)

    # ===============================
    # BOTTOM: SOC
    # ===============================
    fig.add_trace(go.Scatter(
        x=time_index,
        y=output["soc"][:-1],
        name="SOC (kWh)",
        line=dict(color="purple")
    ), row=2, col=1)

    # SOC constraint lines (only if present)
    if soc_min is not None:
        fig.add_hline(y=soc_min, row=2, col=1, line_dash="dash", line_color="red")

    if soc_max is not None:
        fig.add_hline(y=soc_max, row=2, col=1, line_dash="dash", line_color="red")

    if low_energy_threshold is not None:
        fig.add_hline(
            y=low_energy_threshold,
            row=2, col=1,
            line_dash="dash",
            line_color="orange"
        )

    # ===============================
    # AXES LIMITS (soft defaults)
    # ===============================
    fig.update_yaxes(
        title_text="Power (kW)",
        range=[-15, 15],
        autorange=True,
        row=1, col=1, secondary_y=False
    )

    fig.update_yaxes(
        title_text="Price (c/kWh)",
        autorange=True,
        row=1, col=1, secondary_y=True
    )

    fig.update_yaxes(
        title_text="SOC (kWh)",
        range=[0, 40],
        autorange=True,
        row=2, col=1
    )

    # ===============================
    # GRID (major + minor, pale)
    # ===============================
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
        height=1000,
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