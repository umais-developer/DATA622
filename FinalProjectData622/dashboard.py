"""
dashboard.py - Streamlit Interactive Dashboard

A web-based dashboard for pharmacists to:
  - View demand forecasts per drug
  - See reorder recommendations
  - Explore historical sales patterns
  - Simulate inventory scenarios

Usage:
    streamlit run dashboard.py
"""

import os
import pickle
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from prophet import Prophet

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS
from data_preprocessing import prepare_prophet_data, create_holiday_dataframe
from decision_engine import calculate_reorder_point
from model_training import PROPHET_AVAILABLE


# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="PharmaCast - Inventory Intelligence",
    page_icon="💊",
    layout="wide",
)

# =============================================================================
# LOAD DATA
# =============================================================================
@st.cache_data
def load_sales_data():
    return pd.read_csv("data/pharmacy_sales.csv", parse_dates=["date"])

@st.cache_resource
def load_model(drug_name):
    model_path = f"models/{drug_name}_model.pkl"
    if os.path.exists(model_path):
        with open(model_path, "rb") as f:
            return pickle.load(f)
    return None

@st.cache_data
def load_recommendations():
    path = "outputs/reorder_recommendations.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


# =============================================================================
# SIDEBAR
# =============================================================================
st.sidebar.title("💊 PharmaCast")
st.sidebar.markdown("*Intelligent Inventory Management*")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigation",
    ["📊 Dashboard", "🔮 Forecasts", "📦 Reorder Alerts", "📈 EDA Explorer"],
)

# =============================================================================
# DASHBOARD PAGE
# =============================================================================
if page == "📊 Dashboard":
    st.title("📊 Pharmacy Inventory Dashboard")
    st.markdown("Real-time overview of inventory health and demand forecasts.")

    try:
        df = load_sales_data()
        rec_df = load_recommendations()
    except FileNotFoundError:
        st.error("⚠️ Data not found. Please run `python run_pipeline.py` first!")
        st.stop()

    if rec_df is not None:
        # KPI Cards
        col1, col2, col3, col4 = st.columns(4)
        critical = (rec_df["urgency"] == "CRITICAL").sum()
        high = (rec_df["urgency"] == "HIGH").sum()
        total_cost = rec_df["order_cost"].sum()
        total_drugs = len(rec_df)

        col1.metric("🔴 Critical Items", critical)
        col2.metric("🟠 High Priority", high)
        col3.metric("💰 Total Order Cost", f"${total_cost:,.2f}")
        col4.metric("💊 Drugs Tracked", total_drugs)

        st.divider()

        # Recommendations Table
        st.subheader("📦 Current Reorder Recommendations")

        def color_urgency(val):
            colors = {"CRITICAL": "#ff4444", "HIGH": "#ff8c00", "MEDIUM": "#ffd700", "LOW": "#44ff44"}
            return f"background-color: {colors.get(val, '#ffffff')}"

        styled_df = rec_df[["drug_name", "urgency", "action", "order_quantity", "order_cost",
                            "days_stock_remaining", "forecast_30d_demand"]].copy()
        styled_df.columns = ["Drug", "Urgency", "Action", "Order Qty", "Cost ($)",
                            "Days Left", "30-Day Demand"]
        st.dataframe(
            styled_df.style.applymap(color_urgency, subset=["Urgency"]),
            use_container_width=True,
            hide_index=True,
        )

    # Recent Sales Trend
    st.subheader("📈 Total Daily Sales (Last 90 Days)")
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=90)]
    daily_total = recent.groupby("date")["units_sold"].sum().reset_index()

    fig = px.line(daily_total, x="date", y="units_sold",
                  labels={"date": "Date", "units_sold": "Total Units Sold"})
    fig.update_traces(line_color="#2196F3")
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# FORECAST PAGE
# =============================================================================
elif page == "🔮 Forecasts":
    st.title("🔮 Demand Forecasts")

    try:
        df = load_sales_data()
    except FileNotFoundError:
        st.error("⚠️ Data not found. Run the pipeline first!")
        st.stop()

    drug_name = st.selectbox("Select Drug", list(DRUG_CATALOG.keys()))
    model = load_model(drug_name)

    if model is None:
        st.warning("Model not found. Run `python run_pipeline.py` first.")
        st.stop()

    # Generate forecast
    prophet_df = prepare_prophet_data(df, drug_name)

    # For the dashboard, we want to forecast BEYOND all available data
    # So we pass the full dataset to the model and forecast 30 days past the end
    if PROPHET_AVAILABLE:
        future = model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS, freq="D")
        forecast = model.predict(future)
    else:
        # For Holt-Winters wrapper, we need to re-fit on full data for dashboard use
        from model_training import HoltWintersWrapper
        dash_model = HoltWintersWrapper()
        dash_model.fit(prophet_df)
        future = dash_model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS)
        forecast = dash_model.predict(future)

    # Drop any NaN rows from forecast
    forecast = forecast.dropna(subset=["yhat"]).copy()

    # Identify future dates (beyond historical data)
    last_historical = prophet_df["ds"].max()
    future_mask = forecast["ds"] > last_historical

    # Plot
    fig = go.Figure()

    # Historical data
    fig.add_trace(go.Scatter(
        x=prophet_df["ds"], y=prophet_df["y"],
        name="Historical Sales", mode="lines",
        line=dict(color="#2196F3", width=1),
    ))

    # Forecast
    fig.add_trace(go.Scatter(
        x=forecast[future_mask]["ds"], y=forecast[future_mask]["yhat"],
        name="Forecast", mode="lines",
        line=dict(color="#FF5722", width=2, dash="dash"),
    ))

    # Confidence interval
    fig.add_trace(go.Scatter(
        x=forecast[future_mask]["ds"], y=forecast[future_mask]["yhat_upper"],
        mode="lines", line=dict(width=0), showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=forecast[future_mask]["ds"], y=forecast[future_mask]["yhat_lower"],
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(255,87,34,0.15)", name="80% Confidence",
    ))

    fig.update_layout(
        title=f"{drug_name} - 30-Day Demand Forecast",
        xaxis_title="Date", yaxis_title="Units Sold",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Forecast summary
    future_forecast = forecast[future_mask].head(FORECAST_HORIZON_DAYS)
    if len(future_forecast) > 0 and future_forecast["yhat"].notna().any():
        col1, col2, col3 = st.columns(3)
        col1.metric("📊 Avg Daily Demand", f"{future_forecast['yhat'].mean():.1f} units")
        col2.metric("📈 Peak Day Demand", f"{future_forecast['yhat'].max():.1f} units")
        col3.metric("📦 Total 30-Day Demand", f"{future_forecast['yhat'].sum():.0f} units")
    else:
        st.warning("No forecast data available for the future period.")

    # Show forecast table
    with st.expander("📋 View Forecast Data"):
        display_df = future_forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        display_df.columns = ["Date", "Predicted", "Lower Bound", "Upper Bound"]
        display_df["Predicted"] = display_df["Predicted"].round(1)
        display_df["Lower Bound"] = display_df["Lower Bound"].round(1)
        display_df["Upper Bound"] = display_df["Upper Bound"].round(1)
        st.dataframe(display_df, use_container_width=True, hide_index=True)


# =============================================================================
# REORDER ALERTS PAGE
# =============================================================================
elif page == "📦 Reorder Alerts":
    st.title("📦 Reorder Alerts & Inventory Simulation")

    try:
        rec_df = load_recommendations()
        df = load_sales_data()
    except FileNotFoundError:
        st.error("⚠️ Run the pipeline first!")
        st.stop()

    if rec_df is None:
        st.warning("No recommendations found. Run the pipeline.")
        st.stop()

    drug_name = st.selectbox("Select Drug", list(DRUG_CATALOG.keys()))
    drug_rec = rec_df[rec_df["drug_name"] == drug_name].iloc[0]
    drug_config = DRUG_CATALOG[drug_name]

    # Alert card
    urgency_colors = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    st.markdown(f"""
    ### {urgency_colors.get(drug_rec['urgency'], '⚪')} {drug_rec['action']}
    **{drug_name.replace('_', ' ')}** — {drug_rec['urgency']} Priority

    | Metric | Value |
    |--------|-------|
    | Order Quantity | **{drug_rec['order_quantity']} units** |
    | Estimated Cost | **${drug_rec['order_cost']:.2f}** |
    | Current Stock | ~{drug_rec['current_stock_est']} units |
    | Days of Stock Left | {drug_rec['days_stock_remaining']:.0f} days |
    | 30-Day Demand Forecast | {drug_rec['forecast_30d_demand']} units |
    | Reorder Point | {drug_rec['reorder_point']} units |
    """)

    # Inventory simulation
    st.subheader("📉 Stock Depletion Simulation")
    model = load_model(drug_name)
    if model:
        prophet_df = prepare_prophet_data(df, drug_name)

        if PROPHET_AVAILABLE:
            future = model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS, freq="D")
            forecast = model.predict(future)
        else:
            from model_training import HoltWintersWrapper
            dash_model = HoltWintersWrapper()
            dash_model.fit(prophet_df)
            future = dash_model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS)
            forecast = dash_model.predict(future)

        forecast = forecast.dropna(subset=["yhat"]).copy()
        last_historical = prophet_df["ds"].max()
        future_mask = forecast["ds"] > last_historical
        future_forecast = forecast[future_mask].head(FORECAST_HORIZON_DAYS).copy()

        # Simulate
        starting_stock = drug_rec["current_stock_est"]
        cumulative_demand = future_forecast["yhat"].clip(lower=0).cumsum()
        future_forecast["stock_level"] = starting_stock - cumulative_demand

        rop = calculate_reorder_point(drug_config, future_forecast["yhat"].clip(lower=0).mean())

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=future_forecast["ds"], y=future_forecast["stock_level"],
            name="Projected Stock", fill="tozeroy",
            line=dict(color="#2196F3", width=2),
            fillcolor="rgba(33,150,243,0.1)",
        ))
        fig.add_hline(y=rop, line_dash="dash", line_color="orange",
                      annotation_text=f"Reorder Point ({int(rop)})")
        fig.add_hline(y=0, line_color="red", line_width=2,
                      annotation_text="STOCKOUT")

        fig.update_layout(
            title=f"Inventory Projection: {drug_name}",
            xaxis_title="Date", yaxis_title="Units in Stock",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# EDA EXPLORER PAGE
# =============================================================================
elif page == "📈 EDA Explorer":
    st.title("📈 Exploratory Data Analysis")

    try:
        df = load_sales_data()
    except FileNotFoundError:
        st.error("⚠️ Data not found!")
        st.stop()

    # Drug selection
    selected_drugs = st.multiselect(
        "Select Drugs to Compare",
        list(DRUG_CATALOG.keys()),
        default=list(DRUG_CATALOG.keys())[:3],
    )

    if not selected_drugs:
        st.warning("Select at least one drug.")
        st.stop()

    # Time series comparison
    st.subheader("Daily Sales Comparison")
    fig = go.Figure()
    for drug in selected_drugs:
        drug_df = df[df["drug_name"] == drug]
        # Weekly rolling average for cleaner visualization
        rolling = drug_df.set_index("date")["units_sold"].rolling(7).mean()
        fig.add_trace(go.Scatter(
            x=rolling.index, y=rolling.values,
            name=drug.replace("_", " "), mode="lines",
        ))

    fig.update_layout(
        title="7-Day Rolling Average Sales",
        xaxis_title="Date", yaxis_title="Units Sold (7-day avg)",
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Day of week analysis
    st.subheader("Day of Week Patterns")
    filtered = df[df["drug_name"].isin(selected_drugs)]
    filtered = filtered.copy()
    filtered["day_name"] = filtered["date"].dt.day_name()
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    fig = px.box(
        filtered, x="day_name", y="units_sold", color="drug_name",
        category_orders={"day_name": day_order},
        labels={"day_name": "Day", "units_sold": "Units Sold", "drug_name": "Drug"},
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

    # Monthly trends
    st.subheader("Monthly Demand Trends")
    filtered_monthly = filtered.copy()
    filtered_monthly["month"] = filtered_monthly["date"].dt.to_period("M").astype(str)
    monthly_agg = filtered_monthly.groupby(["month", "drug_name"])["units_sold"].sum().reset_index()

    fig = px.bar(
        monthly_agg, x="month", y="units_sold", color="drug_name",
        barmode="group",
        labels={"month": "Month", "units_sold": "Total Units", "drug_name": "Drug"},
    )
    fig.update_layout(height=400, xaxis_tickangle=45)
    st.plotly_chart(fig, use_container_width=True)