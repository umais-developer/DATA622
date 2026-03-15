"""
data_generator.py - Synthetic Pharmacy Sales Data Engine (Objective A)

Generates HIPAA-compliant, realistic pharmacy sales logs that exhibit:
  - Yearly seasonality (flu season, allergy season, etc.)
  - Weekly seasonality (weekend dips)
  - Long-term trend (growing customer base)
  - Holiday effects (demand spikes/drops around major holidays)
  - Poisson-distributed noise (proper count data distribution)

Data sources used for calibration:
  - CDC FluView seasonal curves
  - General prescription volume patterns from CMS public data
  - US holiday calendar via `holidays` library

Usage:
    python data_generator.py
"""

import os
import numpy as np
import pandas as pd
import holidays
from datetime import datetime, timedelta

from config import (
    DRUG_CATALOG,
    SEASONAL_PROFILES,
    WEEKLY_PATTERN,
    SIMULATION_START_DATE,
    SIMULATION_END_DATE,
    TREND_GROWTH_RATE,
)


def get_holiday_effect(date: datetime, us_holidays: dict) -> float:
    """
    Returns a demand multiplier based on proximity to US holidays.
    - On the holiday itself: demand drops (pharmacy may be closed/reduced hours)
    - 1-2 days before: slight spike (people refill early)
    """
    # Check if date is a holiday
    if date in us_holidays:
        return 0.3  # Significant drop on holiday

    # Check day before holiday
    next_day = date + timedelta(days=1)
    if next_day in us_holidays:
        return 1.25  # Pre-holiday spike

    # Check 2 days before
    two_days = date + timedelta(days=2)
    if two_days in us_holidays:
        return 1.10

    return 1.0  # No holiday effect


def generate_drug_sales(drug_name: str, drug_config: dict, seed: int = 42) -> pd.DataFrame:
    """
    Generate daily sales data for a single drug using Poisson noise.

    The demand signal is computed deterministically from seasonality, weekly
    patterns, trends, and holidays. The final count is drawn from a Poisson
    distribution centered on the computed demand (with optional overdispersion
    via a Negative Binomial approximation).

    Parameters
    ----------
    drug_name : str
        Name of the drug.
    drug_config : dict
        Configuration dict from DRUG_CATALOG.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: date, drug_name, units_sold, category
    """
    rng = np.random.RandomState(seed)

    # Extract years from simulation range
    start_year = int(SIMULATION_START_DATE[:4])
    end_year = int(SIMULATION_END_DATE[:4])
    us_holidays_cal = holidays.US(years=list(range(start_year, end_year + 1)))

    dates = pd.date_range(start=SIMULATION_START_DATE, end=SIMULATION_END_DATE, freq="D")
    base = drug_config["base_daily_demand"]
    profile = SEASONAL_PROFILES[drug_config["seasonal_profile"]]
    noise_scale = drug_config.get("noise_scale", 0.15)

    records = []
    for i, date in enumerate(dates):
        # 1. Base demand
        demand = base

        # 2. Apply yearly seasonality
        month_multiplier = profile[date.month]
        demand *= month_multiplier

        # 3. Apply weekly pattern (weekend dip)
        day_multiplier = WEEKLY_PATTERN[date.dayofweek]
        demand *= day_multiplier

        # 4. Apply long-term growth trend
        trend_multiplier = 1.0 + (TREND_GROWTH_RATE * i)
        demand *= trend_multiplier

        # 5. Apply holiday effects
        holiday_mult = get_holiday_effect(date, us_holidays_cal)
        demand *= holiday_mult

        # 6. Poisson noise for count data (variance scales with mean)
        # Use Negative Binomial for overdispersion control
        demand = max(demand, 0.1)  # Ensure positive lambda
        overdispersion = 1.0 + noise_scale  # >1 means overdispersed
        # Negative Binomial parameterized via mean and dispersion
        n_param = demand / (overdispersion - 1) if overdispersion > 1 else demand * 100
        p_param = 1.0 / overdispersion if overdispersion > 1 else 0.99
        units_sold = rng.negative_binomial(max(1, int(round(n_param))), min(0.99, max(0.01, p_param)))

        records.append({
            "date": date,
            "drug_name": drug_name,
            "units_sold": int(units_sold),
            "category": drug_config["category"],
        })

    return pd.DataFrame(records)


def generate_all_data() -> pd.DataFrame:
    """
    Generate sales data for all drugs in the catalog.

    Returns
    -------
    pd.DataFrame
        Combined DataFrame with all drug sales.
    """
    print("=" * 60)
    print("  PHARMACY SYNTHETIC DATA GENERATOR")
    print(f"  Date Range: {SIMULATION_START_DATE} to {SIMULATION_END_DATE}")
    print("=" * 60)

    all_frames = []
    for i, (drug_name, drug_config) in enumerate(DRUG_CATALOG.items()):
        print(f"  Generating data for: {drug_name:<30} ", end="")
        df = generate_drug_sales(drug_name, drug_config, seed=42 + i)
        all_frames.append(df)
        total_units = df["units_sold"].sum()
        print(f"| {len(df):>4} days | {total_units:>6,} total units")

    combined = pd.concat(all_frames, ignore_index=True)
    print("-" * 60)
    print(f"  Total records generated: {len(combined):,}")
    print(f"  Date range: {SIMULATION_START_DATE} to {SIMULATION_END_DATE}")
    print(f"  Drugs simulated: {len(DRUG_CATALOG)}")
    print("=" * 60)

    return combined


def save_data(df: pd.DataFrame, output_dir: str = "data") -> str:
    """Save generated data to CSV."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "pharmacy_sales.csv")
    df.to_csv(filepath, index=False)
    print(f"\n  Data saved to: {filepath}")
    return filepath


if __name__ == "__main__":
    df = generate_all_data()
    save_data(df)

    # Print summary statistics
    print("\n  SUMMARY STATISTICS PER DRUG:")
    print("-" * 60)
    summary = df.groupby("drug_name")["units_sold"].agg(["mean", "std", "min", "max"])
    summary.columns = ["Avg Daily", "Std Dev", "Min", "Max"]
    print(summary.to_string())
