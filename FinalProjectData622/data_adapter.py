"""
data_adapter.py - Production Data Loading & Validation Layer

Abstracts data loading so the pipeline works with both synthetic and real
pharmacy data. Pharmacists only need to:
  1. Place their sales CSV at the configured path
  2. Set use_synthetic_data: false in pharmacy_config.yaml

Supports:
  - CSV file loading with validation
  - Optional current inventory CSV
  - Automatic drug discovery from data
  - Data quality checks and error reporting

Usage:
    from data_adapter import load_pharmacy_data, validate_data, get_current_inventory
"""

import os
import yaml
import pandas as pd
import numpy as np
from datetime import datetime


# =============================================================================
# CONFIGURATION LOADER
# =============================================================================
_CONFIG_PATH = "pharmacy_config.yaml"
_DEFAULT_CONFIG = {
    "pharmacy_name": "PharmaCast Demo",
    "data_source": {
        "type": "csv",
        "sales_csv": "data/pharmacy_sales.csv",
        "inventory_csv": None,
    },
    "use_synthetic_data": True,
}


def load_yaml_config(config_path: str = _CONFIG_PATH) -> dict:
    """
    Load pharmacy configuration from YAML file.
    Falls back to defaults if file doesn't exist.
    """
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f) or {}
        # Merge with defaults (user values override)
        config = {**_DEFAULT_CONFIG, **user_config}
        if "data_source" in user_config:
            config["data_source"] = {**_DEFAULT_CONFIG["data_source"], **user_config["data_source"]}
        return config
    return _DEFAULT_CONFIG.copy()


def save_yaml_config(config: dict, config_path: str = _CONFIG_PATH):
    """Write updated config back to YAML file."""
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def is_synthetic_mode(config: dict = None) -> bool:
    """Check if the system is running in synthetic data mode."""
    if config is None:
        config = load_yaml_config()
    return config.get("use_synthetic_data", True)


def get_pharmacy_name(config: dict = None) -> str:
    """Get the configured pharmacy name."""
    if config is None:
        config = load_yaml_config()
    return config.get("pharmacy_name", "PharmaCast Demo")


# =============================================================================
# DATA VALIDATION
# =============================================================================
REQUIRED_COLUMNS = ["date", "drug_name", "units_sold", "category"]


def validate_data(df: pd.DataFrame) -> dict:
    """
    Validate pharmacy sales data for required format and quality.

    Returns a dict with:
      - valid: bool
      - errors: list of critical issues (data cannot be used)
      - warnings: list of non-critical issues (data usable but imperfect)
      - summary: dict of data statistics
    """
    errors = []
    warnings = []

    # Check required columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {missing_cols}")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": {}}

    # Check data types
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        try:
            df["date"] = pd.to_datetime(df["date"])
        except Exception:
            errors.append("Column 'date' cannot be parsed as datetime.")

    if not pd.api.types.is_numeric_dtype(df["units_sold"]):
        errors.append("Column 'units_sold' must be numeric.")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": {}}

    # Check for negative sales
    neg_count = (df["units_sold"] < 0).sum()
    if neg_count > 0:
        warnings.append(f"{neg_count} rows have negative units_sold (will be clipped to 0).")

    # Check for missing values
    null_counts = df[REQUIRED_COLUMNS].isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            warnings.append(f"Column '{col}' has {count} missing values.")

    # Check date range
    date_range = (df["date"].max() - df["date"].min()).days
    if date_range < 90:
        warnings.append(f"Only {date_range} days of data. Prophet works best with 365+ days.")
    elif date_range < 365:
        warnings.append(f"{date_range} days of data. Yearly seasonality may not be well captured.")

    # Check for gaps
    drugs = df["drug_name"].unique()
    for drug in drugs:
        drug_df = df[df["drug_name"] == drug].sort_values("date")
        date_diffs = drug_df["date"].diff().dt.days
        gaps = date_diffs[date_diffs > 1]
        if len(gaps) > 5:
            warnings.append(f"Drug '{drug}' has {len(gaps)} date gaps (missing days).")

    summary = {
        "n_records": len(df),
        "n_drugs": len(drugs),
        "drug_names": sorted(drugs.tolist()),
        "date_range": f"{df['date'].min().date()} to {df['date'].max().date()}",
        "date_span_days": date_range,
        "categories": sorted(df["category"].unique().tolist()),
    }

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }


# =============================================================================
# DATA LOADING
# =============================================================================
def load_pharmacy_data(config: dict = None) -> pd.DataFrame:
    """
    Load pharmacy sales data from the configured source.
    Validates the data and prints a report.

    Parameters
    ----------
    config : dict, optional
        Configuration dict. If None, loads from pharmacy_config.yaml.

    Returns
    -------
    pd.DataFrame
        Validated sales data with columns: date, drug_name, units_sold, category
    """
    if config is None:
        config = load_yaml_config()

    source = config.get("data_source", {})
    csv_path = source.get("sales_csv", "data/pharmacy_sales.csv")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Sales data file not found: {csv_path}\n"
            f"Please place your sales CSV at this path.\n"
            f"See data/sample_format.csv for the required format."
        )

    print(f"  Loading data from: {csv_path}")
    df = pd.read_csv(csv_path, parse_dates=["date"])

    # Validate
    result = validate_data(df)

    if not result["valid"]:
        error_msg = "\n".join(f"  ERROR: {e}" for e in result["errors"])
        raise ValueError(
            f"Data validation failed:\n{error_msg}\n\n"
            f"See data/sample_format.csv for the required format."
        )

    # Print warnings
    for w in result["warnings"]:
        print(f"  WARNING: {w}")

    # Print summary
    s = result["summary"]
    print(f"  Loaded {s['n_records']:,} records | {s['n_drugs']} drugs | {s['date_range']}")

    # Clean data: clip negative sales
    df["units_sold"] = df["units_sold"].clip(lower=0)

    return df


# =============================================================================
# DRUG DISCOVERY
# =============================================================================
def detect_drugs(df: pd.DataFrame) -> dict:
    """
    Auto-discover drugs from the data and build a basic catalog.
    Used when pharmacists provide real data without editing the drug catalog.

    Returns a dict compatible with DRUG_CATALOG format.
    """
    catalog = {}
    for drug_name in df["drug_name"].unique():
        drug_df = df[df["drug_name"] == drug_name]
        avg_demand = drug_df["units_sold"].mean()
        category = drug_df["category"].iloc[0] if "category" in drug_df.columns else "Unknown"

        catalog[drug_name] = {
            "category": category,
            "base_daily_demand": round(avg_demand, 1),
            "unit_cost": 1.00,  # Default — pharmacist should update
            "shelf_life_days": 365,  # Default
            "lead_time_days": 2,  # Default
            "safety_stock_days": 7,  # Default
            "seasonal_profile": "stable",  # Will be learned by Prophet
            "noise_scale": 0.15,
            "changepoint_prior_scale": 0.05,
            "seasonality_prior_scale": 10.0,
            "holidays_prior_scale": 10.0,
        }

    return catalog


def validate_inventory_csv(df: pd.DataFrame, known_drugs: list) -> dict:
    """
    Validate optional inventory CSV upload.
    Expected columns: drug_name, units_on_hand
    """
    errors = []
    warnings = []

    required = ["drug_name", "units_on_hand"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {missing}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    if not pd.api.types.is_numeric_dtype(df["units_on_hand"]):
        errors.append("Column 'units_on_hand' must be numeric.")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    inv_drugs = set(df["drug_name"].unique())
    sales_drugs = set(known_drugs)
    unmatched = inv_drugs - sales_drugs
    if unmatched:
        warnings.append(f"Inventory drugs not in sales data (will be ignored): {sorted(unmatched)}")

    return {"valid": True, "errors": errors, "warnings": warnings}


# =============================================================================
# INVENTORY LOADING
# =============================================================================
def get_current_inventory(drug_name: str, config: dict = None) -> int:
    """
    Get current inventory level for a drug.

    If an inventory CSV is configured, reads from it.
    Otherwise returns None (caller should use simulated estimate).

    Expected inventory CSV format:
        drug_name,units_on_hand
        Amoxicillin_500mg,250
        Metformin_500mg,400
    """
    if config is None:
        config = load_yaml_config()

    inventory_path = config.get("data_source", {}).get("inventory_csv")

    if inventory_path and os.path.exists(inventory_path):
        inv_df = pd.read_csv(inventory_path)
        if "drug_name" in inv_df.columns and "units_on_hand" in inv_df.columns:
            match = inv_df[inv_df["drug_name"] == drug_name]
            if not match.empty:
                return int(match["units_on_hand"].iloc[0])

    # No inventory data available — return None so caller uses estimate
    return None
