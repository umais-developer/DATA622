"""
decision_engine.py - Inventory Reorder Decision Engine (Objective C)

Translates Prophet model predictions into actionable business decisions with
full economic cost analysis for wastage and understocking:

  - Calculates reorder points based on lead time + safety stock
  - Computes wastage cost (expired inventory due to overstocking)
  - Computes understocking cost (lost sales, emergency orders, patient harm)
  - Computes holding cost (storage, insurance, capital)
  - Generates "Order Now" triggers when projected stock falls below threshold
  - Simulates inventory levels with shelf life expiration tracking
  - Produces total cost of ownership analysis per drug

Usage:
    python decision_engine.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS, ORDER_ROUNDING, COST_PARAMS
from data_preprocessing import load_data, prepare_prophet_data, create_holiday_dataframe
from data_adapter import get_current_inventory, load_yaml_config
from model_training import train_all_drugs


# =============================================================================
# COST FUNCTIONS
# =============================================================================
def calculate_wastage_cost(
    excess_units: float,
    unit_cost: float,
    shelf_life_days: int,
    days_in_stock: float,
) -> dict:
    """
    Calculate the cost of inventory wastage due to expiration.

    Parameters
    ----------
    excess_units : float
        Units that will expire before being sold.
    unit_cost : float
        Cost per unit of the drug.
    shelf_life_days : int
        Shelf life in days.
    days_in_stock : float
        Estimated days inventory has been in stock.

    Returns
    -------
    dict
        Breakdown of wastage costs.
    """
    # Units at risk of expiration
    expiration_risk = max(0, days_in_stock / shelf_life_days)  # 0 to 1 scale
    units_wasted = max(0, excess_units * min(1.0, expiration_risk))

    # Cost components
    product_loss = units_wasted * unit_cost * COST_PARAMS["wastage_fraction_of_unit_cost"]
    disposal_cost = units_wasted * COST_PARAMS["wastage_disposal_cost_per_unit"]
    total_wastage_cost = product_loss + disposal_cost

    return {
        "units_at_risk": round(excess_units, 0),
        "units_wasted_est": round(units_wasted, 0),
        "expiration_risk_pct": round(expiration_risk * 100, 1),
        "product_loss_cost": round(product_loss, 2),
        "disposal_cost": round(disposal_cost, 2),
        "total_wastage_cost": round(total_wastage_cost, 2),
    }


def calculate_understocking_cost(
    stockout_units: float,
    unit_cost: float,
    avg_daily_demand: float,
    lead_time_days: int,
) -> dict:
    """
    Calculate the cost of understocking (stockouts).

    Parameters
    ----------
    stockout_units : float
        Units of unmet demand during the forecast period.
    unit_cost : float
        Cost per unit of the drug.
    avg_daily_demand : float
        Average daily demand.
    lead_time_days : int
        Supplier lead time in days.

    Returns
    -------
    dict
        Breakdown of understocking costs.
    """
    # Lost sales cost (units that couldn't be sold)
    lost_sale_cost = stockout_units * unit_cost * COST_PARAMS["stockout_penalty_multiplier"]

    # Emergency order cost (rush orders to cover gap)
    emergency_units = min(stockout_units, avg_daily_demand * lead_time_days)
    emergency_cost = emergency_units * unit_cost * COST_PARAMS["emergency_order_surcharge"]

    # Customer loss cost (patients going elsewhere)
    stockout_days = stockout_units / max(avg_daily_demand, 1)
    customer_loss = stockout_days * COST_PARAMS["lost_customer_cost"]

    total_understocking_cost = lost_sale_cost + emergency_cost + customer_loss

    return {
        "stockout_units": round(stockout_units, 0),
        "stockout_days_est": round(stockout_days, 1),
        "lost_sale_cost": round(lost_sale_cost, 2),
        "emergency_order_cost": round(emergency_cost, 2),
        "customer_loss_cost": round(customer_loss, 2),
        "total_understocking_cost": round(total_understocking_cost, 2),
    }


def calculate_holding_cost(
    avg_inventory: float,
    unit_cost: float,
    days: int = FORECAST_HORIZON_DAYS,
) -> dict:
    """
    Calculate inventory holding/carrying cost.

    Parameters
    ----------
    avg_inventory : float
        Average units in inventory over the period.
    unit_cost : float
        Cost per unit.
    days : int
        Number of days in the period.

    Returns
    -------
    dict
        Holding cost breakdown.
    """
    daily_rate = COST_PARAMS["daily_holding_rate"]
    holding_cost = avg_inventory * unit_cost * daily_rate * days

    return {
        "avg_inventory_units": round(avg_inventory, 0),
        "holding_cost": round(holding_cost, 2),
        "daily_holding_rate": daily_rate,
    }


def calculate_total_cost_of_ownership(
    wastage: dict, understocking: dict, holding: dict, order_cost: float,
) -> dict:
    """
    Calculate the Total Cost of Ownership (TCO) for inventory decisions.
    """
    tco = (
        wastage["total_wastage_cost"]
        + understocking["total_understocking_cost"]
        + holding["holding_cost"]
        + order_cost
    )
    return {
        "wastage_cost": wastage["total_wastage_cost"],
        "understocking_cost": understocking["total_understocking_cost"],
        "holding_cost": holding["holding_cost"],
        "order_cost": order_cost,
        "total_cost_of_ownership": round(tco, 2),
    }


# =============================================================================
# INVENTORY SIMULATION WITH EXPIRATION TRACKING
# =============================================================================
def simulate_inventory_with_expiration(
    forecast_demand: np.ndarray,
    starting_stock: int,
    shelf_life_days: int,
    avg_stock_age_days: int = 60,
) -> dict:
    """
    Simulate inventory over the forecast horizon with shelf life tracking.

    Returns daily stock levels, stockout events, and expiration events.
    """
    n_days = len(forecast_demand)
    stock = float(starting_stock)
    daily_stock = []
    stockout_units_total = 0
    expired_units_total = 0

    # Track batches: (units, days_remaining)
    # Assume current stock has some age distribution
    remaining_life = max(1, shelf_life_days - avg_stock_age_days)
    batches = [(stock, remaining_life)]

    for day in range(n_days):
        demand = max(0, forecast_demand[day])

        # Age all batches
        aged_batches = []
        for units, life in batches:
            new_life = life - 1
            if new_life <= 0:
                expired_units_total += units  # Expired
            else:
                aged_batches.append((units, new_life))
        batches = aged_batches

        # Fulfill demand (FIFO - oldest first)
        remaining_demand = demand
        fulfilled_batches = []
        for units, life in batches:
            if remaining_demand <= 0:
                fulfilled_batches.append((units, life))
            elif units <= remaining_demand:
                remaining_demand -= units  # Fully consumed
            else:
                fulfilled_batches.append((units - remaining_demand, life))
                remaining_demand = 0
        batches = fulfilled_batches

        if remaining_demand > 0:
            stockout_units_total += remaining_demand

        stock = sum(u for u, _ in batches)
        daily_stock.append(stock)

    return {
        "daily_stock": np.array(daily_stock),
        "stockout_units": stockout_units_total,
        "expired_units": expired_units_total,
        "final_stock": daily_stock[-1] if daily_stock else starting_stock,
    }


# =============================================================================
# REORDER POINT & ORDER QUANTITY
# =============================================================================
def calculate_reorder_point(drug_config: dict, avg_daily_demand: float) -> float:
    """
    Calculate the Reorder Point (ROP).
    ROP = (Lead Time x Average Daily Demand) + Safety Stock
    """
    lead_time = drug_config["lead_time_days"]
    safety_days = drug_config["safety_stock_days"]
    rop = (lead_time * avg_daily_demand) + (safety_days * avg_daily_demand)
    return rop


def calculate_order_quantity(
    forecast_demand: float,
    current_stock: float,
    reorder_point: float,
    drug_config: dict,
) -> int:
    """
    Calculate order quantity balancing wastage vs understocking.
    """
    target_stock = forecast_demand + (drug_config["safety_stock_days"] * (forecast_demand / FORECAST_HORIZON_DAYS))
    order_qty = max(0, target_stock - current_stock)

    if order_qty > 0:
        order_qty = int(np.ceil(order_qty / ORDER_ROUNDING) * ORDER_ROUNDING)

    return order_qty


# =============================================================================
# MAIN RECOMMENDATION ENGINE
# =============================================================================
def generate_reorder_recommendations(results: dict, drug_catalog: dict = None) -> pd.DataFrame:
    """
    Generate reorder recommendations with full cost analysis.
    Includes wastage cost, understocking cost, and total cost of ownership.
    """
    print("\n" + "=" * 70)
    print("  INVENTORY REORDER RECOMMENDATIONS")
    print("  With Wastage & Understocking Cost Analysis")
    print("  Generated for next 30-day period")
    print("=" * 70)

    catalog = drug_catalog or DRUG_CATALOG
    recommendations = []

    for drug_name, result in results.items():
        drug_config = catalog[drug_name]
        forecast = result["forecast"]
        train_df = result["train_df"]

        # Get the 30-day forecast (future period only)
        last_train_date = train_df["ds"].max()
        future_forecast = forecast[forecast["ds"] > last_train_date].head(FORECAST_HORIZON_DAYS)

        # Calculate demand metrics
        forecast_demand_array = future_forecast["yhat"].clip(lower=0).values
        forecast_total_demand = forecast_demand_array.sum()
        forecast_peak_demand = forecast_demand_array.max()
        avg_daily_demand = forecast_demand_array.mean()

        # Use upper bound for conservative ordering (80th percentile)
        conservative_demand = future_forecast["yhat_upper"].clip(lower=0).sum()

        # Calculate reorder point
        rop = calculate_reorder_point(drug_config, avg_daily_demand)

        # Get current stock: use real inventory if available, else estimate
        historical_avg = train_df["y"].mean()
        real_stock = get_current_inventory(drug_name)
        if real_stock is not None:
            simulated_current_stock = real_stock
        else:
            simulated_current_stock = int(historical_avg * 14)

        # Determine order quantity
        days_of_stock_remaining = simulated_current_stock / max(avg_daily_demand, 1)
        order_qty = calculate_order_quantity(
            conservative_demand, simulated_current_stock, rop, drug_config
        )
        order_cost = order_qty * drug_config["unit_cost"]

        # --- COST ANALYSIS ---
        # 1. Run inventory simulation with expiration tracking
        sim = simulate_inventory_with_expiration(
            forecast_demand_array,
            simulated_current_stock,
            drug_config["shelf_life_days"],
        )

        # 2. Wastage cost (excess inventory that may expire)
        excess_after_period = max(0, simulated_current_stock + order_qty - forecast_total_demand)
        wastage = calculate_wastage_cost(
            excess_units=excess_after_period + sim["expired_units"],
            unit_cost=drug_config["unit_cost"],
            shelf_life_days=drug_config["shelf_life_days"],
            days_in_stock=FORECAST_HORIZON_DAYS + 60,  # Assume ~60 days average age
        )

        # 3. Understocking cost
        understocking = calculate_understocking_cost(
            stockout_units=sim["stockout_units"],
            unit_cost=drug_config["unit_cost"],
            avg_daily_demand=avg_daily_demand,
            lead_time_days=drug_config["lead_time_days"],
        )

        # 4. Holding cost
        avg_inventory = (simulated_current_stock + sim["final_stock"]) / 2
        holding = calculate_holding_cost(avg_inventory, drug_config["unit_cost"])

        # 5. Total Cost of Ownership
        tco = calculate_total_cost_of_ownership(wastage, understocking, holding, order_cost)

        # Determine urgency
        if days_of_stock_remaining < drug_config["lead_time_days"]:
            urgency = "CRITICAL"
            action = "ORDER NOW"
        elif days_of_stock_remaining < (drug_config["lead_time_days"] + drug_config["safety_stock_days"]):
            urgency = "HIGH"
            action = "ORDER SOON"
        elif days_of_stock_remaining < 14:
            urgency = "MEDIUM"
            action = "PLAN ORDER"
        else:
            urgency = "LOW"
            action = "MONITOR"

        # Calculate service level and waste rate
        total_possible_sales = forecast_total_demand
        fulfilled_sales = total_possible_sales - sim["stockout_units"]
        service_level = (fulfilled_sales / max(total_possible_sales, 1)) * 100
        waste_rate = (sim["expired_units"] / max(simulated_current_stock + order_qty, 1)) * 100

        rec = {
            "drug_name": drug_name,
            "category": drug_config["category"],
            "action": action,
            "urgency": urgency,
            "order_quantity": order_qty,
            "order_cost": round(order_cost, 2),
            "current_stock_est": simulated_current_stock,
            "days_stock_remaining": round(days_of_stock_remaining, 1),
            "forecast_30d_demand": int(round(forecast_total_demand)),
            "forecast_peak_daily": round(forecast_peak_demand, 1),
            "reorder_point": int(round(rop)),
            # Cost analysis columns
            "wastage_cost": wastage["total_wastage_cost"],
            "understocking_cost": understocking["total_understocking_cost"],
            "holding_cost": holding["holding_cost"],
            "total_cost_of_ownership": tco["total_cost_of_ownership"],
            "service_level_pct": round(service_level, 1),
            "waste_rate_pct": round(waste_rate, 1),
            "expired_units_est": int(sim["expired_units"]),
            "stockout_units_est": int(sim["stockout_units"]),
        }
        recommendations.append(rec)

        # Print formatted recommendation
        emoji = {"CRITICAL": "!", "HIGH": "*", "MEDIUM": "-", "LOW": " "}.get(urgency, " ")
        print(f"\n  [{emoji}] {drug_name}")
        print(f"     Action: {action} | Urgency: {urgency}")
        print(f"     Order Qty: {order_qty} units (${order_cost:.2f})")
        print(f"     Current Stock: ~{simulated_current_stock} units ({days_of_stock_remaining:.0f} days)")
        print(f"     30-Day Forecast: {int(forecast_total_demand)} units | Peak: {forecast_peak_demand:.0f}/day")
        print(f"     --- Cost Analysis ---")
        print(f"     Wastage Cost:       ${wastage['total_wastage_cost']:>8.2f}  (waste rate: {waste_rate:.1f}%)")
        print(f"     Understocking Cost: ${understocking['total_understocking_cost']:>8.2f}  (service level: {service_level:.1f}%)")
        print(f"     Holding Cost:       ${holding['holding_cost']:>8.2f}")
        print(f"     Order Cost:         ${order_cost:>8.2f}")
        print(f"     TOTAL COST:         ${tco['total_cost_of_ownership']:>8.2f}")

    rec_df = pd.DataFrame(recommendations)
    print("\n" + "=" * 70)
    total_cost = rec_df["order_cost"].sum()
    total_tco = rec_df["total_cost_of_ownership"].sum()
    total_wastage = rec_df["wastage_cost"].sum()
    total_understocking = rec_df["understocking_cost"].sum()
    critical_count = (rec_df["urgency"] == "CRITICAL").sum()
    avg_service = rec_df["service_level_pct"].mean()
    avg_waste = rec_df["waste_rate_pct"].mean()

    print(f"  PORTFOLIO COST SUMMARY")
    print(f"  {'='*40}")
    print(f"  Total Order Cost:         ${total_cost:>10,.2f}")
    print(f"  Total Wastage Cost:       ${total_wastage:>10,.2f}")
    print(f"  Total Understocking Cost: ${total_understocking:>10,.2f}")
    print(f"  Total Cost of Ownership:  ${total_tco:>10,.2f}")
    print(f"  {'='*40}")
    print(f"  Avg Service Level:  {avg_service:.1f}%  (Target: {COST_PARAMS['target_service_level']*100:.0f}%)")
    print(f"  Avg Waste Rate:     {avg_waste:.1f}%  (Target: <{COST_PARAMS['target_waste_rate']*100:.0f}%)")
    print(f"  Critical Items:     {critical_count}")
    print("=" * 70)

    return rec_df


def generate_inventory_simulation_plot(results: dict, output_dir: str = "outputs", drug_catalog: dict = None):
    """
    Generate inventory simulation visualization with expiration tracking.
    """
    catalog = drug_catalog or DRUG_CATALOG
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    n_drugs = len(results)
    n_cols = 2
    n_rows = max(1, (n_drugs + 1) // 2)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(16, 4 * n_rows))
    if n_drugs == 1:
        axes = np.array([[axes]]) if n_cols == 1 else np.array([axes])
    elif n_rows == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle("30-Day Inventory Simulation: Stock Levels with Expiration Risk",
                 fontsize=16, fontweight="bold")

    for idx, (drug_name, result) in enumerate(results.items()):
        ax = axes[idx // n_cols, idx % n_cols]
        drug_config = catalog[drug_name]
        forecast = result["forecast"]
        train_df = result["train_df"]

        last_train_date = train_df["ds"].max()
        future = forecast[forecast["ds"] > last_train_date].head(FORECAST_HORIZON_DAYS).copy()

        # Simulate stock depletion
        historical_avg = train_df["y"].mean()
        starting_stock = int(historical_avg * 14)
        future["stock_level"] = starting_stock - future["yhat"].clip(lower=0).cumsum()
        future["stock_upper"] = starting_stock - future["yhat_lower"].clip(lower=0).cumsum()
        future["stock_lower"] = starting_stock - future["yhat_upper"].clip(lower=0).cumsum()

        # Reorder point line
        rop = calculate_reorder_point(drug_config, historical_avg)

        ax.plot(future["ds"], future["stock_level"], "b-", linewidth=2, label="Projected Stock")
        ax.fill_between(future["ds"], future["stock_lower"], future["stock_upper"],
                       alpha=0.2, color="blue")
        ax.axhline(y=rop, color="orange", linestyle="--", linewidth=1.5, label=f"Reorder Point ({int(rop)})")
        ax.axhline(y=0, color="red", linestyle="-", linewidth=2, label="Stockout")

        # Mark stockout zone
        stockout_mask = future["stock_level"] < 0
        if stockout_mask.any():
            ax.fill_between(future["ds"], future["stock_level"], 0,
                           where=stockout_mask, alpha=0.3, color="red", label="Stockout Zone")

        ax.set_title(f"{drug_name.replace('_', ' ')} (Shelf life: {drug_config['shelf_life_days']}d)", fontsize=10)
        ax.set_ylabel("Units in Stock")
        ax.legend(fontsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    # Hide unused subplot axes
    for idx in range(n_drugs, n_rows * n_cols):
        axes[idx // n_cols, idx % n_cols].set_visible(False)

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "inventory_simulation.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved: {output_dir}/inventory_simulation.png")


def generate_cost_analysis_plot(rec_df: pd.DataFrame, output_dir: str = "outputs"):
    """
    Generate a stacked bar chart showing cost breakdown per drug.
    """
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    fig, axes = plt.subplots(1, 2, figsize=(18, 7))

    # --- Plot 1: Cost Breakdown Stacked Bar ---
    ax = axes[0]
    drugs = rec_df["drug_name"]
    x = np.arange(len(drugs))
    width = 0.6

    ax.bar(x, rec_df["order_cost"], width, label="Order Cost", color="#3498db")
    ax.bar(x, rec_df["holding_cost"], width, bottom=rec_df["order_cost"],
           label="Holding Cost", color="#f39c12")
    ax.bar(x, rec_df["wastage_cost"], width,
           bottom=rec_df["order_cost"] + rec_df["holding_cost"],
           label="Wastage Cost", color="#e74c3c")
    ax.bar(x, rec_df["understocking_cost"], width,
           bottom=rec_df["order_cost"] + rec_df["holding_cost"] + rec_df["wastage_cost"],
           label="Understocking Cost", color="#9b59b6")

    ax.set_xticks(x)
    ax.set_xticklabels([d.replace("_", "\n") for d in drugs], fontsize=8)
    ax.set_ylabel("Cost ($)")
    ax.set_title("Total Cost of Ownership Breakdown by Drug", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)

    # --- Plot 2: Service Level vs Waste Rate ---
    ax2 = axes[1]
    colors = {"CRITICAL": "#e74c3c", "HIGH": "#f39c12", "MEDIUM": "#f1c40f", "LOW": "#2ecc71"}
    c = [colors.get(u, "#95a5a6") for u in rec_df["urgency"]]

    scatter = ax2.scatter(
        rec_df["waste_rate_pct"], rec_df["service_level_pct"],
        c=c, s=150, edgecolors="black", linewidth=0.5, zorder=5
    )
    for i, drug in enumerate(drugs):
        ax2.annotate(drug.replace("_", " "), (rec_df["waste_rate_pct"].iloc[i], rec_df["service_level_pct"].iloc[i]),
                    fontsize=7, ha="center", va="bottom", xytext=(0, 8), textcoords="offset points")

    # Target zones
    ax2.axhline(y=COST_PARAMS["target_service_level"] * 100, color="green", linestyle="--",
                alpha=0.7, label=f"Service Target ({COST_PARAMS['target_service_level']*100:.0f}%)")
    ax2.axvline(x=COST_PARAMS["target_waste_rate"] * 100, color="red", linestyle="--",
                alpha=0.7, label=f"Waste Target (<{COST_PARAMS['target_waste_rate']*100:.0f}%)")

    ax2.set_xlabel("Waste Rate (%)")
    ax2.set_ylabel("Service Level (%)")
    ax2.set_title("Service Level vs Waste Rate by Drug", fontsize=13, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.set_xlim(-0.5, max(rec_df["waste_rate_pct"].max() * 1.2, 5))
    ax2.set_ylim(min(rec_df["service_level_pct"].min() - 5, 85), 102)

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "cost_analysis.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/cost_analysis.png")


if __name__ == "__main__":
    # Train models
    results = train_all_drugs()

    # Generate recommendations with cost analysis
    rec_df = generate_reorder_recommendations(results)

    # Save recommendations
    os.makedirs("outputs", exist_ok=True)
    rec_df.to_csv("outputs/reorder_recommendations.csv", index=False)
    print(f"\n  Recommendations saved to: outputs/reorder_recommendations.csv")

    # Generate plots
    generate_inventory_simulation_plot(results)
    generate_cost_analysis_plot(rec_df)
