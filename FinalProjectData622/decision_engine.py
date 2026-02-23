"""
decision_engine.py - Inventory Reorder Decision Engine (Objective C)

Translates Prophet model predictions into actionable business decisions:
  - Calculates reorder points based on lead time + safety stock
  - Generates "Order Now" triggers when projected stock falls below threshold
  - Computes optimal order quantities
  - Simulates inventory levels over the forecast horizon

Usage:
    python decision_engine.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS, ORDER_ROUNDING
from data_preprocessing import load_data, prepare_prophet_data, create_holiday_dataframe
from model_training import train_all_drugs


def calculate_reorder_point(drug_config: dict, avg_daily_demand: float) -> float:
    """
    Calculate the Reorder Point (ROP).

    ROP = (Lead Time × Average Daily Demand) + Safety Stock
    Safety Stock = Safety Stock Days × Average Daily Demand
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
    Calculate how much to order.

    Uses Economic Order Quantity approximation:
    Order enough to cover forecast_horizon + safety stock, minus what's on hand.
    Rounded up to nearest ORDER_ROUNDING units.
    """
    target_stock = forecast_demand + (drug_config["safety_stock_days"] * (forecast_demand / FORECAST_HORIZON_DAYS))
    order_qty = max(0, target_stock - current_stock)

    # Round up to nearest batch size
    if order_qty > 0:
        order_qty = int(np.ceil(order_qty / ORDER_ROUNDING) * ORDER_ROUNDING)

    return order_qty


def generate_reorder_recommendations(results: dict) -> pd.DataFrame:
    """
    Generate reorder recommendations for all drugs.

    Simulates a scenario where we check stock today and decide what to order.

    Parameters
    ----------
    results : dict
        Training results from train_all_drugs().

    Returns
    -------
    pd.DataFrame
        Recommendations with columns: drug, action, quantity, urgency, etc.
    """
    print("\n" + "=" * 70)
    print("  INVENTORY REORDER RECOMMENDATIONS")
    print("  Generated for next 30-day period")
    print("=" * 70)

    recommendations = []

    for drug_name, result in results.items():
        drug_config = DRUG_CATALOG[drug_name]
        forecast = result["forecast"]
        train_df = result["train_df"]

        # Get the 30-day forecast (future period only)
        last_train_date = train_df["ds"].max()
        future_forecast = forecast[forecast["ds"] > last_train_date].head(FORECAST_HORIZON_DAYS)

        # Calculate demand metrics
        forecast_total_demand = future_forecast["yhat"].clip(lower=0).sum()
        forecast_peak_demand = future_forecast["yhat"].clip(lower=0).max()
        avg_daily_demand = future_forecast["yhat"].clip(lower=0).mean()

        # Use upper bound for conservative ordering (80th percentile)
        conservative_demand = future_forecast["yhat_upper"].clip(lower=0).sum()

        # Calculate reorder point
        rop = calculate_reorder_point(drug_config, avg_daily_demand)

        # Simulate current stock (assume we have ~2 weeks of average supply on hand)
        historical_avg = train_df["y"].mean()
        simulated_current_stock = int(historical_avg * 14)

        # Determine if we need to order
        days_of_stock_remaining = simulated_current_stock / max(avg_daily_demand, 1)
        order_qty = calculate_order_quantity(
            conservative_demand, simulated_current_stock, rop, drug_config
        )

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

        # Calculate cost
        order_cost = order_qty * drug_config["unit_cost"]

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
        }
        recommendations.append(rec)

        # Print formatted recommendation
        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(urgency, "⚪")
        print(f"\n  {emoji} {drug_name}")
        print(f"     Action: {action} | Urgency: {urgency}")
        print(f"     Order Qty: {order_qty} units (${order_cost:.2f})")
        print(f"     Current Stock: ~{simulated_current_stock} units ({days_of_stock_remaining:.0f} days)")
        print(f"     30-Day Forecast: {int(forecast_total_demand)} units | Peak: {forecast_peak_demand:.0f}/day")

    rec_df = pd.DataFrame(recommendations)
    print("\n" + "=" * 70)
    total_cost = rec_df["order_cost"].sum()
    critical_count = (rec_df["urgency"] == "CRITICAL").sum()
    print(f"  TOTAL ORDER COST: ${total_cost:,.2f}")
    print(f"  CRITICAL ITEMS: {critical_count}")
    print("=" * 70)

    return rec_df


def generate_inventory_simulation_plot(results: dict, output_dir: str = "outputs"):
    """
    Generate an inventory simulation visualization showing projected stock levels.
    """
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    fig, axes = plt.subplots(4, 2, figsize=(16, 16))
    fig.suptitle("30-Day Inventory Simulation: Projected Stock Levels",
                 fontsize=16, fontweight="bold")

    for idx, (drug_name, result) in enumerate(results.items()):
        ax = axes[idx // 2, idx % 2]
        drug_config = DRUG_CATALOG[drug_name]
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
        ax.set_title(drug_name.replace("_", " "), fontsize=11)
        ax.set_ylabel("Units in Stock")
        ax.legend(fontsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "inventory_simulation.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved: {output_dir}/inventory_simulation.png")


if __name__ == "__main__":
    # Train models
    results = train_all_drugs()

    # Generate recommendations
    rec_df = generate_reorder_recommendations(results)

    # Save recommendations
    os.makedirs("outputs", exist_ok=True)
    rec_df.to_csv("outputs/reorder_recommendations.csv", index=False)
    print(f"\n  Recommendations saved to: outputs/reorder_recommendations.csv")

    # Generate inventory simulation plot
    generate_inventory_simulation_plot(results)
