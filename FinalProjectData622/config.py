"""
config.py - Central configuration for the Pharmacy Inventory Management System.

Contains drug catalog, demand parameters, seasonality profiles, business rules,
and cost functions for wastage and understocking analysis.

Configuration priority:
  1. pharmacy_config.yaml (if present) — pharmacist-editable, no code changes needed
  2. Environment variables (DATA_DIR, MODELS_DIR, OUTPUTS_DIR)
  3. Hardcoded defaults below (used for synthetic data / demo mode)
"""

import os
import numpy as np

# =============================================================================
# DRUG CATALOG
# Each drug has realistic parameters for demand simulation and inventory rules.
# =============================================================================
DRUG_CATALOG = {
    "Amoxicillin_500mg": {
        "category": "Antibiotic",
        "base_daily_demand": 18,
        "unit_cost": 0.45,
        "shelf_life_days": 365,
        "lead_time_days": 2,
        "safety_stock_days": 5,
        "seasonal_profile": "winter_spike",  # Flu/cold season
        "noise_scale": 0.20,  # Poisson overdispersion factor
        # Prophet hyperparameters (tuned per drug)
        "changepoint_prior_scale": 0.1,
        "seasonality_prior_scale": 15.0,
        "holidays_prior_scale": 15.0,
    },
    "Metformin_500mg": {
        "category": "Diabetes",
        "base_daily_demand": 30,
        "unit_cost": 0.12,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "stable",  # Chronic med - steady demand
        "noise_scale": 0.10,
        "changepoint_prior_scale": 0.01,  # Stable trend
        "seasonality_prior_scale": 5.0,
        "holidays_prior_scale": 5.0,
    },
    "Lisinopril_10mg": {
        "category": "Blood Pressure",
        "base_daily_demand": 25,
        "unit_cost": 0.08,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "stable",
        "noise_scale": 0.12,
        "changepoint_prior_scale": 0.01,
        "seasonality_prior_scale": 5.0,
        "holidays_prior_scale": 5.0,
    },
    "Albuterol_Inhaler": {
        "category": "Respiratory",
        "base_daily_demand": 9,
        "unit_cost": 25.00,
        "shelf_life_days": 365,
        "lead_time_days": 3,
        "safety_stock_days": 5,
        "seasonal_profile": "winter_spike",
        "noise_scale": 0.25,
        "changepoint_prior_scale": 0.1,
        "seasonality_prior_scale": 15.0,
        "holidays_prior_scale": 10.0,
    },
    "Cetirizine_10mg": {
        "category": "Allergy",
        "base_daily_demand": 12,
        "unit_cost": 0.15,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 5,
        "seasonal_profile": "spring_spike",  # Allergy season
        "noise_scale": 0.20,
        "changepoint_prior_scale": 0.15,  # Sharper seasonal transitions
        "seasonality_prior_scale": 20.0,   # Strong seasonality
        "holidays_prior_scale": 5.0,
    },
    "Azithromycin_250mg": {
        "category": "Antibiotic",
        "base_daily_demand": 10,
        "unit_cost": 1.20,
        "shelf_life_days": 365,
        "lead_time_days": 2,
        "safety_stock_days": 5,
        "seasonal_profile": "winter_spike",
        "noise_scale": 0.22,
        "changepoint_prior_scale": 0.1,
        "seasonality_prior_scale": 15.0,
        "holidays_prior_scale": 10.0,
    },
    "Omeprazole_20mg": {
        "category": "Gastrointestinal",
        "base_daily_demand": 20,
        "unit_cost": 0.10,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "holiday_spike",  # Overeating seasons
        "noise_scale": 0.15,
        "changepoint_prior_scale": 0.05,
        "seasonality_prior_scale": 12.0,
        "holidays_prior_scale": 15.0,  # Strong holiday effect
    },
    "Sertraline_50mg": {
        "category": "Mental Health",
        "base_daily_demand": 15,
        "unit_cost": 0.18,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 10,
        "seasonal_profile": "winter_sad",  # Seasonal affective disorder
        "noise_scale": 0.12,
        "changepoint_prior_scale": 0.05,
        "seasonality_prior_scale": 10.0,
        "holidays_prior_scale": 5.0,
    },
}

# =============================================================================
# SEASONALITY MULTIPLIER FUNCTIONS
# Maps month (1-12) to a demand multiplier for each seasonal profile.
# =============================================================================
SEASONAL_PROFILES = {
    "winter_spike": {
        1: 1.60, 2: 1.45, 3: 1.15, 4: 0.90, 5: 0.85, 6: 0.80,
        7: 0.80, 8: 0.85, 9: 0.90, 10: 1.00, 11: 1.20, 12: 1.50,
    },
    "spring_spike": {
        1: 0.70, 2: 0.80, 3: 1.20, 4: 1.60, 5: 1.70, 6: 1.40,
        7: 1.00, 8: 0.85, 9: 0.90, 10: 0.80, 11: 0.70, 12: 0.70,
    },
    "stable": {
        1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.00,
        7: 1.00, 8: 1.00, 9: 1.00, 10: 1.00, 11: 1.00, 12: 1.00,
    },
    "holiday_spike": {
        1: 1.10, 2: 0.95, 3: 0.90, 4: 0.90, 5: 0.90, 6: 0.95,
        7: 1.05, 8: 0.95, 9: 0.90, 10: 0.95, 11: 1.30, 12: 1.50,
    },
    "winter_sad": {
        1: 1.25, 2: 1.20, 3: 1.10, 4: 1.00, 5: 0.90, 6: 0.85,
        7: 0.85, 8: 0.85, 9: 0.95, 10: 1.05, 11: 1.15, 12: 1.25,
    },
}

# =============================================================================
# WEEKLY PATTERN (Day of week multipliers: Mon=0, Sun=6)
# Reflects clinic closures on weekends
# =============================================================================
WEEKLY_PATTERN = {
    0: 1.15,  # Monday - post-weekend catchup
    1: 1.05,  # Tuesday
    2: 1.00,  # Wednesday
    3: 1.00,  # Thursday
    4: 1.10,  # Friday - before-weekend stocking
    5: 0.55,  # Saturday - half day
    6: 0.30,  # Sunday - minimal/closed
}

# =============================================================================
# SIMULATION PARAMETERS (Updated to 2024-2026 for current analysis)
# =============================================================================
SIMULATION_START_DATE = "2024-01-01"
SIMULATION_END_DATE = "2026-02-26"  # ~2.15 years of data through today
TREND_GROWTH_RATE = 0.0003  # ~0.03% daily growth (~11% annual)

# =============================================================================
# MODEL PARAMETERS
# =============================================================================
FORECAST_HORIZON_DAYS = 30
TRAIN_TEST_SPLIT_DAYS = 60  # Last 60 days held out for testing

# =============================================================================
# BUSINESS RULES FOR REORDER DECISIONS
# =============================================================================
REORDER_CONFIDENCE_THRESHOLD = 0.80  # Use 80th percentile for safety
ORDER_ROUNDING = 10  # Round orders up to nearest 10 units

# =============================================================================
# COST FUNCTIONS FOR WASTAGE & UNDERSTOCKING
# Aligned with proposal Section 6: Asymmetric Cost Functions
#
# Wastage (Section 6.2): C_w = max(F-A, 0) * (c_unit * p_exp + c_hold)
# Stockout (Section 6.3): C_s = max(A-F, 0) * (alpha * c_unit + c_emergency + c_churn)
# Total (Section 6.4):    L   = C_w + C_s
# =============================================================================
COST_PARAMS = {
    # --- Proposal Section 6.3: Asymmetric penalty multiplier ---
    # alpha=10: a stockout is ~10x more costly than holding one excess unit
    # "encodes the clinical imperative" per proposal
    "asymmetric_alpha": 10,

    # --- Proposal Section 6.3: Per-unit stockout cost components ---
    # c_emergency: emergency reorder cost per stockout unit ($15-50 amortized)
    "emergency_reorder_cost": 1.50,
    # c_churn: patient switching to competitor per stockout unit
    "patient_churn_cost": 5.00,

    # --- Proposal Section 6.2: Wastage cost components ---
    # p_exp: probability of expiration before sale (estimated by shelf life)
    "expiration_prob_short_shelf": 0.05,   # 365-day shelf life drugs
    "expiration_prob_long_shelf": 0.02,    # 730-day shelf life drugs
    # c_hold: daily holding cost per unit ($0.02-$0.10/unit/day per proposal)
    "daily_holding_cost_per_unit": 0.03,   # $0.03/unit/day (proposal example)

    # --- Holding cost: carrying inventory ---
    "annual_holding_rate": 0.20,           # 20% of unit cost per year
    "daily_holding_rate": 0.20 / 365,      # Daily rate derived from annual

    # --- Service level targets (proposal Section 7.4) ---
    "target_service_level": 0.95,          # >95% fill rate target
    "target_waste_rate": 0.02,             # <2% waste rate target
}

# =============================================================================
# CONFIGURABLE PATHS (overridable via environment variables)
# =============================================================================
DATA_DIR = os.environ.get("PHARMACAST_DATA_DIR", "data")
MODELS_DIR = os.environ.get("PHARMACAST_MODELS_DIR", "models")
OUTPUTS_DIR = os.environ.get("PHARMACAST_OUTPUTS_DIR", "outputs")


# =============================================================================
# RUNTIME CATALOG OVERRIDE (used by dashboard upload feature)
# =============================================================================
_CATALOG_OVERRIDE = None


def get_active_catalog() -> dict:
    """Return the currently active drug catalog (override or default)."""
    if _CATALOG_OVERRIDE is not None:
        return _CATALOG_OVERRIDE
    return DRUG_CATALOG


def set_catalog_override(catalog: dict):
    """Override DRUG_CATALOG at runtime (used by upload feature)."""
    global _CATALOG_OVERRIDE
    _CATALOG_OVERRIDE = catalog


def clear_catalog_override():
    """Reset to default catalog."""
    global _CATALOG_OVERRIDE
    _CATALOG_OVERRIDE = None
