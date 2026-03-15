"""
data_preprocessing.py - Data Cleaning & Feature Engineering

Prepares raw pharmacy sales data for Prophet modeling:
  - Renames columns to Prophet format (ds, y)
  - Adds holiday dataframe
  - Performs train/test split
  - Generates EDA visualizations

Usage:
    python data_preprocessing.py
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import holidays as holidays_lib

from config import (
    DRUG_CATALOG,
    TRAIN_TEST_SPLIT_DAYS,
    SIMULATION_START_DATE,
    SIMULATION_END_DATE,
    DATA_DIR,
    get_active_catalog,
)
from data_adapter import load_pharmacy_data, load_yaml_config


def load_data(filepath: str = None) -> pd.DataFrame:
    """
    Load pharmacy sales data.
    Uses data_adapter for validation and config-driven path resolution.
    Falls back to direct CSV load if data_adapter is unavailable.
    """
    if filepath is not None:
        # Direct path override (e.g., from tests)
        df = pd.read_csv(filepath, parse_dates=["date"])
        print(f"Loaded {len(df):,} records from {filepath}")
        return df

    config = load_yaml_config()
    return load_pharmacy_data(config)


def prepare_prophet_data(df: pd.DataFrame, drug_name: str) -> pd.DataFrame:
    """
    Filter data for a specific drug and format for Prophet.

    Prophet requires columns named 'ds' (datestamp) and 'y' (target).
    """
    drug_df = df[df["drug_name"] == drug_name][["date", "units_sold"]].copy()
    drug_df = drug_df.rename(columns={"date": "ds", "units_sold": "y"})
    drug_df = drug_df.sort_values("ds").reset_index(drop=True)
    return drug_df


def create_holiday_dataframe() -> pd.DataFrame:
    """
    Create a holiday DataFrame for Prophet.

    Prophet can incorporate holidays as special events that affect demand.
    We include major US holidays that impact pharmacy operations.
    """
    start_year = int(SIMULATION_START_DATE[:4])
    end_year = int(SIMULATION_END_DATE[:4])
    us_holidays = holidays_lib.US(years=list(range(start_year, end_year + 2)))

    holiday_df = pd.DataFrame(
        [{"ds": date, "holiday": name} for date, name in us_holidays.items()]
    )
    holiday_df["ds"] = pd.to_datetime(holiday_df["ds"])

    # Add lower/upper windows: effect starts 1 day before, lasts 0 days after
    holiday_df["lower_window"] = -1
    holiday_df["upper_window"] = 0

    return holiday_df


def train_test_split(df: pd.DataFrame, test_days: int = TRAIN_TEST_SPLIT_DAYS):
    """
    Split time-series data into train and test sets.

    Uses the last `test_days` as the test set (no shuffling - time series!).
    """
    cutoff_date = df["ds"].max() - pd.Timedelta(days=test_days)
    train = df[df["ds"] <= cutoff_date].copy()
    test = df[df["ds"] > cutoff_date].copy()

    print(f"  Train set: {len(train)} days ({train['ds'].min().date()} to {train['ds'].max().date()})")
    print(f"  Test set:  {len(test)} days ({test['ds'].min().date()} to {test['ds'].max().date()})")

    return train, test


def generate_eda_plots(df: pd.DataFrame, output_dir: str = "outputs"):
    """
    Generate Exploratory Data Analysis visualizations.
    """
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    date_range_str = f"{df['date'].min().strftime('%b %Y')} - {df['date'].max().strftime('%b %Y')}"

    # --- Plot 1: Daily Sales Time Series for All Drugs ---
    catalog = get_active_catalog()
    n_drugs = len(catalog)
    n_cols = 2
    n_rows = max(1, (n_drugs + 1) // 2)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(16, 3.5 * n_rows), sharex=True)
    if n_drugs == 1:
        axes = np.array([[axes]])
    elif n_rows == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle(f"Daily Sales by Drug ({date_range_str})", fontsize=16, fontweight="bold")

    for idx, drug_name in enumerate(catalog.keys()):
        ax = axes[idx // n_cols, idx % n_cols]
        drug_df = df[df["drug_name"] == drug_name]
        ax.plot(drug_df["date"], drug_df["units_sold"], linewidth=0.6, alpha=0.8)
        ax.set_title(drug_name.replace("_", " "), fontsize=11)
        ax.set_ylabel("Units Sold")
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    for idx in range(n_drugs, n_rows * n_cols):
        axes[idx // n_cols, idx % n_cols].set_visible(False)

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eda_daily_sales.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eda_daily_sales.png")

    # --- Plot 2: Monthly Aggregated Heatmap ---
    pivot_data = df.copy()
    pivot_data["month"] = pivot_data["date"].dt.to_period("M").astype(str)
    monthly = pivot_data.groupby(["drug_name", "month"])["units_sold"].sum().reset_index()
    heatmap_data = monthly.pivot(index="drug_name", columns="month", values="units_sold")

    fig, ax = plt.subplots(figsize=(20, 6))
    sns.heatmap(heatmap_data, cmap="YlOrRd", ax=ax, linewidths=0.5)
    ax.set_title("Monthly Total Sales Heatmap", fontsize=14, fontweight="bold")
    ax.set_xlabel("Month")
    ax.set_ylabel("Drug")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eda_monthly_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eda_monthly_heatmap.png")

    # --- Plot 3: Day-of-Week Distribution ---
    fig, ax = plt.subplots(figsize=(10, 6))
    df_copy = df.copy()
    df_copy["day_name"] = df_copy["date"].dt.day_name()
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    sns.boxplot(data=df_copy, x="day_name", y="units_sold", order=day_order, ax=ax, palette="Set2")
    ax.set_title("Sales Distribution by Day of Week (All Drugs)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Day of Week")
    ax.set_ylabel("Units Sold")
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eda_day_of_week.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eda_day_of_week.png")

    print("  EDA plots generated successfully!")


if __name__ == "__main__":
    # Load data
    df = load_data()

    # Show summary
    print("\nDataset shape:", df.shape)
    print("\nDrugs in dataset:", df["drug_name"].unique().tolist())

    # Generate EDA plots
    print("\nGenerating EDA visualizations...")
    generate_eda_plots(df)

    # Demo: prepare one drug for Prophet
    print("\nExample - preparing Amoxicillin_500mg for Prophet:")
    prophet_df = prepare_prophet_data(df, "Amoxicillin_500mg")
    print(prophet_df.head(10))

    print("\nHoliday DataFrame (first 10):")
    holidays_df = create_holiday_dataframe()
    print(holidays_df.head(10))
