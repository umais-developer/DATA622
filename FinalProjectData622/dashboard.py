"""
dashboard.py - Streamlit Interactive Dashboard

A web-based dashboard for pharmacists to:
  - View demand forecasts per drug
  - See reorder recommendations with cost analysis
  - Explore wastage vs understocking trade-offs
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

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS, COST_PARAMS, get_active_catalog, set_catalog_override, clear_catalog_override, DATA_DIR, MODELS_DIR, OUTPUTS_DIR
from data_preprocessing import prepare_prophet_data, create_holiday_dataframe
from decision_engine import calculate_reorder_point
from model_training import PROPHET_AVAILABLE
from data_adapter import load_yaml_config, is_synthetic_mode, get_pharmacy_name, validate_data, detect_drugs, save_yaml_config, validate_inventory_csv
from cloud_storage import download_from_gcs, upload_to_gcs, is_gcs_enabled
from auth_manager import require_auth, logout, is_auth_configured
from user_db import (
    list_users, add_user, remove_user, update_user_role,
    create_invite, get_pending_invites, is_admin,
)


# =============================================================================
# STARTUP: Restore persisted data from GCS (runs once per container)
# =============================================================================
@st.cache_resource
def _startup_gcs_sync():
    restored = download_from_gcs()
    if restored:
        st.cache_data.clear()
    return restored

_startup_gcs_sync()


# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="PharmaCast - Inventory Intelligence",
    page_icon="💊",
    layout="wide",
)

# =============================================================================
# AUTHENTICATION GATE
# =============================================================================
# Returns user info dict if authenticated, None if auth is not configured (demo mode).
# If auth is configured but user is not logged in, this shows the login page and stops.
current_user = require_auth()

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

@st.cache_data
def load_evaluation_metrics():
    path = "outputs/evaluation_metrics.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    return None

@st.cache_data
def load_cv_metrics():
    path = "outputs/cross_validation_metrics.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


# =============================================================================
# SIDEBAR
# =============================================================================
st.sidebar.title("💊 PharmaCast")
st.sidebar.markdown("*Intelligent Inventory Management*")

# User info and logout
if current_user is not None:
    st.sidebar.markdown(f"**{current_user.get('name', current_user['email'])}**")
    st.sidebar.caption(current_user["email"])
    if st.sidebar.button("Logout", use_container_width=True):
        logout()
    st.sidebar.divider()

# Data source indicator
_config = load_yaml_config()
if is_synthetic_mode(_config):
    st.sidebar.info("📋 **Data Source:** Synthetic (Demo)")
else:
    st.sidebar.success(f"📋 **Data Source:** {get_pharmacy_name(_config)}")

st.sidebar.divider()

# Build navigation list — admin page only for admin users
_nav_pages = ["📊 Dashboard", "🔮 Forecasts", "📦 Reorder Alerts", "💰 Cost Analysis", "📈 EDA Explorer", "📤 Upload Data"]
if current_user is not None and is_admin(current_user["email"]):
    _nav_pages.append("👤 Admin")

page = st.sidebar.radio(
    "Navigation",
    _nav_pages,
)

# =============================================================================
# DASHBOARD PAGE
# =============================================================================
if page == "📊 Dashboard":
    st.title("📊 Pharmacy Inventory Dashboard")
    st.markdown("Real-time overview of inventory health, demand forecasts, and cost analysis.")

    try:
        df = load_sales_data()
        rec_df = load_recommendations()
        eval_df = load_evaluation_metrics()
    except FileNotFoundError:
        st.error("⚠️ Data not found. Please run `python run_pipeline.py` first!")
        st.stop()

    if rec_df is not None:
        # KPI Cards - Row 1
        col1, col2, col3, col4 = st.columns(4)
        critical = (rec_df["urgency"] == "CRITICAL").sum()
        high = (rec_df["urgency"] == "HIGH").sum()
        total_order_cost = rec_df["order_cost"].sum()
        total_drugs = len(rec_df)

        col1.metric("🔴 Critical Items", critical)
        col2.metric("🟠 High Priority", high)
        col3.metric("💰 Total Order Cost", f"${total_order_cost:,.2f}")
        col4.metric("💊 Drugs Tracked", total_drugs)

        # KPI Cards - Row 2: Cost Analysis
        col5, col6, col7, col8 = st.columns(4)
        total_tco = rec_df["total_cost_of_ownership"].sum()
        total_wastage = rec_df["wastage_cost"].sum()
        total_understocking = rec_df["understocking_cost"].sum()
        avg_service = rec_df["service_level_pct"].mean()

        col5.metric("📉 Total Cost of Ownership", f"${total_tco:,.2f}")
        col6.metric("🗑️ Wastage Cost", f"${total_wastage:,.2f}")
        col7.metric("⚠️ Understocking Cost", f"${total_understocking:,.2f}")
        col8.metric("✅ Avg Service Level", f"{avg_service:.1f}%")

        # KPI Card - Row 3: Asymmetric Loss (Proposal Section 6.4)
        if "asymmetric_loss" in rec_df.columns:
            col9, col10, col11, col12 = st.columns(4)
            total_asym_loss = rec_df["asymmetric_loss"].sum()
            avg_cr = rec_df["critical_ratio"].mean() if "critical_ratio" in rec_df.columns else 0
            col9.metric("⚖️ Asymmetric Loss (L_total)", f"${total_asym_loss:,.2f}")
            col10.metric("📊 Avg Critical Ratio", f"{avg_cr:.4f}")

        st.divider()

        # Recommendations Table
        st.subheader("📦 Current Reorder Recommendations")

        def color_urgency(val):
            colors = {"CRITICAL": "#ff4444", "HIGH": "#ff8c00", "MEDIUM": "#ffd700", "LOW": "#44ff44"}
            return f"background-color: {colors.get(val, '#ffffff')}"

        styled_df = rec_df[["drug_name", "urgency", "action", "order_quantity", "order_cost",
                            "days_stock_remaining", "forecast_30d_demand", "total_cost_of_ownership"]].copy()
        styled_df.columns = ["Drug", "Urgency", "Action", "Order Qty", "Cost ($)",
                            "Days Left", "30-Day Demand", "TCO ($)"]
        st.dataframe(
            styled_df.style.map(color_urgency, subset=["Urgency"]),
            use_container_width=True,
            hide_index=True,
        )

    # Model Performance Summary
    if eval_df is not None:
        st.subheader("🎯 Model Performance Summary")
        col1, col2 = st.columns(2)

        with col1:
            avg_wmape = eval_df["wmape"].mean()
            pass_count = eval_df["target_met"].sum()
            st.metric("Avg wMAPE", f"{avg_wmape:.1f}%", delta=f"{pass_count}/{len(eval_df)} pass")

        with col2:
            avg_coverage = eval_df["coverage_80pct"].mean()
            st.metric("Avg 80% CI Coverage", f"{avg_coverage:.1f}%")

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

    drug_name = st.selectbox("Select Drug", list(get_active_catalog().keys()))
    model = load_model(drug_name)

    if model is None:
        st.warning("Model not found. Run `python run_pipeline.py` first.")
        st.stop()

    # Generate forecast
    prophet_df = prepare_prophet_data(df, drug_name)

    # Extend forecast past the end of ALL data (not just training data)
    days_beyond_train = (prophet_df["ds"].max() - model.history["ds"].max()).days if PROPHET_AVAILABLE else 0
    total_periods = days_beyond_train + FORECAST_HORIZON_DAYS

    if PROPHET_AVAILABLE:
        future = model.make_future_dataframe(periods=total_periods, freq="D")
        forecast = model.predict(future)
    else:
        from model_training import HoltWintersWrapper
        dash_model = HoltWintersWrapper()
        dash_model.fit(prophet_df)
        future = dash_model.make_future_dataframe(periods=total_periods)
        forecast = dash_model.predict(future)

    forecast = forecast.dropna(subset=["yhat"]).copy()
    last_historical = prophet_df["ds"].max()
    future_mask = forecast["ds"] > last_historical

    # Plot
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=prophet_df["ds"], y=prophet_df["y"],
        name="Historical Sales", mode="lines",
        line=dict(color="#2196F3", width=1),
    ))

    fig.add_trace(go.Scatter(
        x=forecast[future_mask]["ds"], y=forecast[future_mask]["yhat"],
        name="Forecast", mode="lines",
        line=dict(color="#FF5722", width=2, dash="dash"),
    ))

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

    drug_name = st.selectbox("Select Drug", list(get_active_catalog().keys()))
    drug_rec = rec_df[rec_df["drug_name"] == drug_name].iloc[0]
    drug_config = get_active_catalog()[drug_name]

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
    | Service Level | {drug_rec['service_level_pct']:.1f}% |
    | Waste Rate | {drug_rec['waste_rate_pct']:.1f}% |
    """)

    # Cost breakdown
    st.subheader("💰 Cost Breakdown")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Order Cost", f"${drug_rec['order_cost']:.2f}")
    col2.metric("Wastage Cost", f"${drug_rec['wastage_cost']:.2f}")
    col3.metric("Understocking Cost", f"${drug_rec['understocking_cost']:.2f}")
    col4.metric("Total TCO", f"${drug_rec['total_cost_of_ownership']:.2f}")

    # Inventory simulation
    st.subheader("📉 Stock Depletion Simulation")
    model = load_model(drug_name)
    if model:
        prophet_df = prepare_prophet_data(df, drug_name)

        # Extend forecast past the end of ALL data (not just training data)
        days_beyond_train = (prophet_df["ds"].max() - model.history["ds"].max()).days if PROPHET_AVAILABLE else 0
        total_periods = days_beyond_train + FORECAST_HORIZON_DAYS

        if PROPHET_AVAILABLE:
            future = model.make_future_dataframe(periods=total_periods, freq="D")
            forecast = model.predict(future)
        else:
            from model_training import HoltWintersWrapper
            dash_model = HoltWintersWrapper()
            dash_model.fit(prophet_df)
            future = dash_model.make_future_dataframe(periods=total_periods)
            forecast = dash_model.predict(future)

        forecast = forecast.dropna(subset=["yhat"]).copy()
        last_historical = prophet_df["ds"].max()
        future_mask = forecast["ds"] > last_historical
        future_forecast = forecast[future_mask].head(FORECAST_HORIZON_DAYS).copy()

        if len(future_forecast) == 0:
            st.warning("No forecast data available for simulation.")
        else:
            # Simulate
            starting_stock = drug_rec["current_stock_est"]
            cumulative_demand = future_forecast["yhat"].clip(lower=0).cumsum()
            future_forecast["stock_level"] = starting_stock - cumulative_demand

            avg_demand = future_forecast["yhat"].clip(lower=0).mean()
            rop = calculate_reorder_point(drug_config, avg_demand if not pd.isna(avg_demand) else 0)

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
# COST ANALYSIS PAGE (NEW)
# =============================================================================
elif page == "💰 Cost Analysis":
    st.title("💰 Wastage & Understocking Cost Analysis")
    st.markdown("Economic analysis of inventory decisions — balancing overstocking waste against stockout penalties.")

    try:
        rec_df = load_recommendations()
    except FileNotFoundError:
        st.error("⚠️ Run the pipeline first!")
        st.stop()

    if rec_df is None:
        st.warning("No recommendations found. Run the pipeline.")
        st.stop()

    # Portfolio summary
    st.subheader("📊 Portfolio Cost Summary")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Order Cost", f"${rec_df['order_cost'].sum():,.2f}")
    col2.metric("Total Wastage Cost", f"${rec_df['wastage_cost'].sum():,.2f}")
    col3.metric("Total Understocking Cost", f"${rec_df['understocking_cost'].sum():,.2f}")
    col4.metric("Total TCO", f"${rec_df['total_cost_of_ownership'].sum():,.2f}")

    st.divider()

    # Cost breakdown stacked bar chart
    st.subheader("📊 Total Cost of Ownership Breakdown by Drug")

    fig = go.Figure()
    drugs = rec_df["drug_name"]

    fig.add_trace(go.Bar(name="Order Cost", x=drugs, y=rec_df["order_cost"],
                         marker_color="#3498db"))
    fig.add_trace(go.Bar(name="Holding Cost", x=drugs, y=rec_df["holding_cost"],
                         marker_color="#f39c12"))
    fig.add_trace(go.Bar(name="Wastage Cost", x=drugs, y=rec_df["wastage_cost"],
                         marker_color="#e74c3c"))
    fig.add_trace(go.Bar(name="Understocking Cost", x=drugs, y=rec_df["understocking_cost"],
                         marker_color="#9b59b6"))

    fig.update_layout(
        barmode="stack",
        xaxis_title="Drug",
        yaxis_title="Cost ($)",
        height=450,
        xaxis_tickangle=45,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Service Level vs Waste Rate scatter
    st.subheader("🎯 Service Level vs Waste Rate")

    color_map = {"CRITICAL": "#e74c3c", "HIGH": "#f39c12", "MEDIUM": "#f1c40f", "LOW": "#2ecc71"}
    rec_df["color"] = rec_df["urgency"].map(color_map)

    fig = px.scatter(
        rec_df, x="waste_rate_pct", y="service_level_pct",
        color="urgency", size="total_cost_of_ownership",
        hover_name="drug_name",
        color_discrete_map=color_map,
        labels={
            "waste_rate_pct": "Waste Rate (%)",
            "service_level_pct": "Service Level (%)",
            "urgency": "Urgency",
            "total_cost_of_ownership": "TCO ($)",
        },
        size_max=40,
    )

    # Target lines
    fig.add_hline(y=COST_PARAMS["target_service_level"] * 100, line_dash="dash",
                  line_color="green", annotation_text=f"Service Target ({COST_PARAMS['target_service_level']*100:.0f}%)")
    fig.add_vline(x=COST_PARAMS["target_waste_rate"] * 100, line_dash="dash",
                  line_color="red", annotation_text=f"Waste Target (<{COST_PARAMS['target_waste_rate']*100:.0f}%)")

    fig.update_layout(height=450)
    st.plotly_chart(fig, use_container_width=True)

    # Detailed cost table
    st.subheader("📋 Detailed Cost Table")
    cost_table = rec_df[[
        "drug_name", "order_cost", "wastage_cost", "understocking_cost",
        "holding_cost", "total_cost_of_ownership", "service_level_pct",
        "waste_rate_pct", "expired_units_est", "stockout_units_est"
    ]].copy()
    cost_table.columns = [
        "Drug", "Order ($)", "Wastage ($)", "Understocking ($)",
        "Holding ($)", "Total TCO ($)", "Service Level %",
        "Waste Rate %", "Expired Units", "Stockout Units"
    ]
    st.dataframe(cost_table, use_container_width=True, hide_index=True)

    # Cost parameters reference
    with st.expander("📖 Cost Model Parameters (Proposal Section 6)"):
        st.markdown(f"""
        **Wastage Cost Function C_w (Section 6.2):**
        - Formula: `C_w = excess_units × (c_unit × p_exp + c_hold)`
        - p_exp (expiration probability): {COST_PARAMS['expiration_prob_short_shelf']} (short shelf) / {COST_PARAMS['expiration_prob_long_shelf']} (long shelf)
        - c_hold (daily holding cost): ${COST_PARAMS['daily_holding_cost_per_unit']:.2f}/unit/day

        **Stockout Cost Function C_s (Section 6.3):**
        - Formula: `C_s = deficit_units × (α × c_unit + c_emergency + c_churn)`
        - α (asymmetric multiplier): **{COST_PARAMS['asymmetric_alpha']}** — stockout is {COST_PARAMS['asymmetric_alpha']}× more costly than holding excess
        - c_emergency (emergency reorder): ${COST_PARAMS['emergency_reorder_cost']:.2f}/unit
        - c_churn (patient loss): ${COST_PARAMS['patient_churn_cost']:.2f}/unit

        **Asymmetric Loss L_total (Section 6.4):**
        - `L(t) = C_w(t) + C_s(t)` — minimized to find optimal order quantity Q*
        - Q* selected at the **critical ratio quantile** of the forecast distribution
        - Because α=10, Q* is near the 80th-90th percentile (prioritizes patient safety)

        **Holding Cost Model:**
        - Annual holding rate: {COST_PARAMS['annual_holding_rate']*100:.0f}% of unit cost
        - Includes: storage, insurance, capital costs

        **Targets (Section 7.4):**
        - Service Level: ≥{COST_PARAMS['target_service_level']*100:.0f}% fill rate
        - Waste Rate: <{COST_PARAMS['target_waste_rate']*100:.0f}%
        """)


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
        list(get_active_catalog().keys()),
        default=list(get_active_catalog().keys())[:3],
    )

    if not selected_drugs:
        st.warning("Select at least one drug.")
        st.stop()

    # Time series comparison
    st.subheader("Daily Sales Comparison")
    fig = go.Figure()
    for drug in selected_drugs:
        drug_df = df[df["drug_name"] == drug]
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


# =============================================================================
# UPLOAD DATA PAGE
# =============================================================================
elif page == "📤 Upload Data":
    st.title("📤 Upload Your Pharmacy Data")
    st.markdown("""
    Upload your pharmacy's sales history to get **customized demand forecasts**
    and **reorder recommendations** tailored to your store.

    No technical knowledge needed -- just upload your CSV and click retrain.
    """)

    # ---- Instructions Section ----
    with st.expander("How to prepare your data", expanded=True):
        st.markdown("""
        **Your CSV file needs these 4 columns:**

        | Column | Description | Example |
        |--------|-------------|---------|
        | `date` | Sale date (YYYY-MM-DD) | 2024-01-15 |
        | `drug_name` | Product name (use underscores for spaces) | Amoxicillin_500mg |
        | `units_sold` | Number of units sold that day | 22 |
        | `category` | Drug category | Antibiotic |

        **Data Requirements:**
        - **Minimum 90 days** of daily sales (3 months)
        - **Recommended 365+ days** for best accuracy (captures seasonal patterns)
        - One row per drug per day
        - Your drugs do NOT need to match the demo drugs -- the system auto-detects them
        """)

        st.markdown("**Example rows:**")
        st.code("""date,drug_name,units_sold,category
2024-01-01,Amoxicillin_500mg,22,Antibiotic
2024-01-01,Metformin_500mg,31,Diabetes
2024-01-02,Amoxicillin_500mg,18,Antibiotic""", language="csv")

    st.divider()

    # ---- File Upload Section ----
    st.subheader("Step 1: Upload Sales Data")

    uploaded_sales = st.file_uploader(
        "Choose your sales CSV file",
        type=["csv"],
        key="sales_csv_upload",
        help="Daily sales data with date, drug_name, units_sold, category columns",
    )

    # ---- Optional Inventory Upload ----
    with st.expander("Optional: Upload Current Inventory Levels"):
        st.markdown("""
        If you know your current stock levels, upload them here for more accurate
        reorder recommendations. Otherwise, the system will estimate based on your
        sales patterns.

        **Format:** Two columns: `drug_name` and `units_on_hand`
        """)
        uploaded_inventory = st.file_uploader(
            "Choose inventory CSV (optional)",
            type=["csv"],
            key="inventory_csv_upload",
        )

    # ---- Validation & Preview ----
    if uploaded_sales is not None:
        try:
            upload_df = pd.read_csv(uploaded_sales, parse_dates=["date"])
        except Exception as e:
            st.error(f"Could not read file: {e}")
            st.stop()

        st.subheader("Step 2: Data Validation")
        validation = validate_data(upload_df)

        if not validation["valid"]:
            st.error("**Data has errors that must be fixed:**")
            for err in validation["errors"]:
                st.error(f"  {err}")
            st.stop()

        # Show warnings
        if validation["warnings"]:
            st.warning("**Warnings** (data is usable, but review these):")
            for w in validation["warnings"]:
                st.warning(f"  {w}")

        # Show summary
        summary = validation["summary"]
        st.success("**Data looks good!** Here is a summary:")

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Records", f"{summary['n_records']:,}")
        col2.metric("Drugs Found", summary["n_drugs"])
        col3.metric("Date Range", f"{summary['date_span_days']} days")

        st.markdown(f"**Date range:** {summary['date_range']}")
        st.markdown(f"**Drugs:** {', '.join(d.replace('_', ' ') for d in summary['drug_names'])}")
        st.markdown(f"**Categories:** {', '.join(summary['categories'])}")

        # Preview data
        with st.expander("Preview uploaded data (first 20 rows)"):
            st.dataframe(upload_df.head(20), use_container_width=True, hide_index=True)

        # Validate optional inventory
        inv_df = None
        if uploaded_inventory is not None:
            try:
                inv_df = pd.read_csv(uploaded_inventory)
                inv_result = validate_inventory_csv(inv_df, summary["drug_names"])
                if not inv_result["valid"]:
                    for err in inv_result["errors"]:
                        st.error(f"Inventory CSV: {err}")
                    inv_df = None
                else:
                    st.success(f"Inventory data loaded: {len(inv_df)} drugs")
                    for w in inv_result["warnings"]:
                        st.warning(f"Inventory: {w}")
            except Exception as e:
                st.error(f"Could not read inventory file: {e}")
                inv_df = None

        st.divider()

        # ---- Pharmacy Name ----
        st.subheader("Step 3: Pharmacy Details")
        pharmacy_name = st.text_input(
            "Your Pharmacy Name (shown in the dashboard header)",
            value="My Pharmacy",
        )

        st.divider()

        # ---- Retrain Button ----
        st.subheader("Step 4: Train Your Models")
        st.markdown(f"""
        This will:
        1. Save your data to the system
        2. Train a forecasting model for each of your **{summary['n_drugs']} drugs**
        3. Generate demand forecasts, reorder alerts, and cost analysis

        **Estimated time: 60-90 seconds** (depends on number of drugs and data size)
        """)

        if st.button("Retrain Models with My Data", type="primary", use_container_width=True):
            from run_pipeline import run_pipeline_steps

            with st.status("Retraining models...", expanded=True) as status:
                # Step 1: Save uploaded CSV to data/
                status.update(label="Saving your data...", state="running")
                os.makedirs(DATA_DIR, exist_ok=True)
                sales_path = os.path.join(DATA_DIR, "pharmacy_sales.csv")
                upload_df.to_csv(sales_path, index=False)

                # Save inventory if provided
                inv_path = None
                if inv_df is not None:
                    inv_path = os.path.join(DATA_DIR, "pharmacy_inventory.csv")
                    inv_df.to_csv(inv_path, index=False)

                # Step 2: Build dynamic catalog from uploaded drugs
                status.update(label="Detecting drugs in your data...", state="running")
                custom_catalog = detect_drugs(upload_df)
                set_catalog_override(custom_catalog)

                # Step 3: Run the pipeline with progress
                progress_bar = st.progress(0, text="Starting pipeline...")

                def on_progress(step, total, message):
                    progress_bar.progress(step / total, text=message)

                try:
                    result = run_pipeline_steps(
                        drug_catalog=custom_catalog,
                        data=upload_df,
                        progress_callback=on_progress,
                    )

                    progress_bar.progress(1.0, text="Complete!")

                    # Step 4: Update config AFTER success (prevents broken state on error)
                    new_config = {
                        "pharmacy_name": pharmacy_name,
                        "use_synthetic_data": False,
                        "data_source": {
                            "type": "csv",
                            "sales_csv": sales_path,
                            "inventory_csv": inv_path,
                        },
                    }
                    save_yaml_config(new_config)

                    # Step 5: Persist to cloud storage
                    if is_gcs_enabled():
                        status.update(label="Saving to cloud storage...", state="running")
                        n_uploaded = upload_to_gcs()
                        st.write(f"Synced {n_uploaded} files to cloud storage.")

                    # Step 6: Clear all Streamlit caches
                    st.cache_data.clear()
                    st.cache_resource.clear()

                    status.update(
                        label=f"Models trained successfully in {result['elapsed']:.0f} seconds!",
                        state="complete",
                        expanded=False,
                    )

                    st.success(f"""
                    **Retraining complete!**
                    - Trained models for **{len(custom_catalog)} drugs** in {result['elapsed']:.0f} seconds
                    - Navigate to other pages using the sidebar to see your results
                    """)
                    st.balloons()

                except Exception as e:
                    status.update(label="Retraining failed", state="error")
                    st.error(f"An error occurred during retraining: {e}")
                    st.exception(e)

    # ---- Show current data source status ----
    st.divider()
    _current_config = load_yaml_config()
    if is_synthetic_mode(_current_config):
        st.info("You are currently viewing **demo data**. Upload your own data above to see real forecasts.")
    else:
        st.success(f"Dashboard is using data from: **{get_pharmacy_name(_current_config)}**")
        if st.button("Reset to Demo Data"):
            # Restore synthetic mode
            demo_config = {
                "pharmacy_name": "PharmaCast Demo",
                "use_synthetic_data": True,
                "data_source": {
                    "type": "csv",
                    "sales_csv": "data/pharmacy_sales.csv",
                    "inventory_csv": None,
                },
            }
            save_yaml_config(demo_config)
            if is_gcs_enabled():
                upload_to_gcs()
            clear_catalog_override()
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()


# =============================================================================
# ADMIN PAGE (only accessible to admin users)
# =============================================================================
elif page == "👤 Admin":
    st.title("👤 User Management")
    st.markdown("Manage who can access the PharmaCast dashboard.")

    if current_user is None or not is_admin(current_user["email"]):
        st.error("You do not have permission to access this page.")
        st.stop()

    # ---- Current Users ----
    st.subheader("Authorized Users")
    users = list_users()

    if users:
        user_data = []
        for email, info in users.items():
            user_data.append({
                "Email": email,
                "Name": info.get("name", ""),
                "Role": info.get("role", "viewer"),
                "Auth Type": ", ".join(info.get("auth_types", [])),
                "Status": info.get("status", ""),
                "Created": info.get("created", "")[:10],
            })

        user_table = pd.DataFrame(user_data)
        st.dataframe(user_table, use_container_width=True, hide_index=True)

    # ---- Add Google User ----
    st.divider()
    st.subheader("Grant Google Access")
    st.markdown("Add a Google account that can sign in directly.")

    with st.form("add_google_user"):
        new_email = st.text_input("Google Email")
        new_name = st.text_input("Name (optional)")
        new_role = st.selectbox("Role", ["viewer", "admin"], index=0)
        add_submitted = st.form_submit_button("Grant Access", use_container_width=True)

    if add_submitted:
        if not new_email or "@" not in new_email:
            st.error("Please enter a valid email address.")
        else:
            add_user(new_email, role=new_role, auth_types=["google"], name=new_name)
            if is_gcs_enabled():
                upload_to_gcs()
            st.success(f"Access granted to **{new_email}**. They can now sign in with Google.")
            st.rerun()

    # ---- Invite Email User ----
    st.divider()
    st.subheader("Invite Email User")
    st.markdown("Generate an invite code for someone who will log in with email/password.")

    with st.form("invite_email_user"):
        invite_email = st.text_input("Email to invite")
        invite_role = st.selectbox("Role", ["viewer", "admin"], index=0, key="invite_role")
        invite_submitted = st.form_submit_button("Generate Invite Code", use_container_width=True)

    if invite_submitted:
        if not invite_email or "@" not in invite_email:
            st.error("Please enter a valid email address.")
        else:
            code = create_invite(invite_email, role=invite_role)
            if is_gcs_enabled():
                upload_to_gcs()
            st.success(f"Invite created for **{invite_email}**")
            st.code(f"Invite Code: {code}", language=None)
            st.info("Share this code with the user. They will enter it on the login page under **Activate Account**.")

    # ---- Pending Invites ----
    pending = get_pending_invites()
    if pending:
        st.divider()
        st.subheader("Pending Invites")
        for email, info in pending.items():
            st.markdown(f"- **{email}** — code: `{info['code']}` (role: {info['role']}, created: {info['created'][:10]})")

    # ---- Remove User ----
    st.divider()
    st.subheader("Remove User")

    removable = [email for email in users if email != "umaisabdullah@gmail.com"]
    if removable:
        with st.form("remove_user"):
            remove_email = st.selectbox("Select user to remove", removable)
            remove_submitted = st.form_submit_button("Remove User", use_container_width=True)

        if remove_submitted:
            if remove_user(remove_email):
                if is_gcs_enabled():
                    upload_to_gcs()
                st.success(f"Removed **{remove_email}**.")
                st.rerun()
            else:
                st.error("Cannot remove the super admin.")
    else:
        st.info("No users to remove (you are the only user).")
