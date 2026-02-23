"""
config.py - Central configuration for the Pharmacy Inventory Management System.

Contains drug catalog, demand parameters, seasonality profiles, and business rules.
"""

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
        "noise_std": 4,
    },
    "Metformin_500mg": {
        "category": "Diabetes",
        "base_daily_demand": 30,
        "unit_cost": 0.12,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "stable",  # Chronic med - steady demand
        "noise_std": 3,
    },
    "Lisinopril_10mg": {
        "category": "Blood Pressure",
        "base_daily_demand": 25,
        "unit_cost": 0.08,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "stable",
        "noise_std": 3,
    },
    "Albuterol_Inhaler": {
        "category": "Respiratory",
        "base_daily_demand": 8,
        "unit_cost": 25.00,
        "shelf_life_days": 365,
        "lead_time_days": 3,
        "safety_stock_days": 5,
        "seasonal_profile": "winter_spike",
        "noise_std": 3,
    },
    "Cetirizine_10mg": {
        "category": "Allergy",
        "base_daily_demand": 12,
        "unit_cost": 0.15,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 5,
        "seasonal_profile": "spring_spike",  # Allergy season
        "noise_std": 3,
    },
    "Azithromycin_250mg": {
        "category": "Antibiotic",
        "base_daily_demand": 10,
        "unit_cost": 1.20,
        "shelf_life_days": 365,
        "lead_time_days": 2,
        "safety_stock_days": 5,
        "seasonal_profile": "winter_spike",
        "noise_std": 3,
    },
    "Omeprazole_20mg": {
        "category": "Gastrointestinal",
        "base_daily_demand": 20,
        "unit_cost": 0.10,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 7,
        "seasonal_profile": "holiday_spike",  # Overeating seasons
        "noise_std": 3,
    },
    "Sertraline_50mg": {
        "category": "Mental Health",
        "base_daily_demand": 15,
        "unit_cost": 0.18,
        "shelf_life_days": 730,
        "lead_time_days": 2,
        "safety_stock_days": 10,
        "seasonal_profile": "winter_sad",  # Seasonal affective disorder
        "noise_std": 2,
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
# SIMULATION PARAMETERS
# =============================================================================
SIMULATION_START_DATE = "2023-01-01"
SIMULATION_END_DATE = "2024-12-31"  # 2 years of data
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
