"""
model_training.py - Time-Series Model Training (Objective B)

Trains forecasting models for each drug to predict daily demand 30 days
into the future. Uses per-drug tuned hyperparameters for optimal accuracy.

Strategy:
  - Attempts to use Facebook Prophet (additive regression model)
  - If Prophet fails (Stan backend issues), falls back to statsmodels
    ExponentialSmoothing with seasonal decomposition

Usage:
    python model_training.py
"""

import os
import pickle
import warnings
import pandas as pd
import numpy as np

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS
from data_preprocessing import (
    load_data,
    prepare_prophet_data,
    create_holiday_dataframe,
    train_test_split,
)

warnings.filterwarnings("ignore")

# ---- Detect which backend is available ----
PROPHET_AVAILABLE = False
try:
    from prophet import Prophet
    # Test if Prophet can actually instantiate (catches Stan backend issues)
    _test = Prophet()
    PROPHET_AVAILABLE = True
    del _test
    print("[INFO] Prophet backend loaded successfully.")
except Exception as e:
    print(f"[WARN] Prophet unavailable ({type(e).__name__}: {e})")
    print("[INFO] Falling back to statsmodels ExponentialSmoothing.")

if not PROPHET_AVAILABLE:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing


# =============================================================================
# PROPHET-BASED MODEL (with per-drug tuned hyperparameters)
# =============================================================================
def build_prophet_model(drug_name: str, holidays_df: pd.DataFrame, drug_config: dict = None) -> "Prophet":
    """Create and configure a Prophet model with drug-specific hyperparameters."""
    if drug_config is None:
        drug_config = DRUG_CATALOG[drug_name]

    model = Prophet(
        growth="linear",
        changepoint_prior_scale=drug_config.get("changepoint_prior_scale", 0.05),
        seasonality_prior_scale=drug_config.get("seasonality_prior_scale", 10.0),
        holidays_prior_scale=drug_config.get("holidays_prior_scale", 10.0),
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        holidays=holidays_df,
        interval_width=0.80,
    )
    model.add_seasonality(name="monthly", period=30.5, fourier_order=5)
    return model


def train_prophet(drug_name, train_df, holidays_df, forecast_periods, drug_config=None):
    """Train using Prophet and return forecast DataFrame + posterior samples."""
    model = build_prophet_model(drug_name, holidays_df, drug_config=drug_config)
    model.fit(train_df)

    future = model.make_future_dataframe(periods=forecast_periods, freq="D")
    forecast = model.predict(future)

    # Generate posterior predictive samples for non-parametric Newsvendor optimization
    # Shape: (nforecast, uncertainty_samples) where default uncertainty_samples=1000
    try:
        posterior = model.predictive_samples(future)
        posterior_samples = posterior["yhat"]  # ndarray (nforecast, 1000)
    except Exception as e:
        print(f"  [WARN] Could not generate posterior samples for {drug_name}: {e}")
        posterior_samples = None

    return model, forecast, posterior_samples


# =============================================================================
# STATSMODELS FALLBACK (ExponentialSmoothing with Holt-Winters)
# =============================================================================
class HoltWintersWrapper:
    """
    Wrapper around statsmodels ExponentialSmoothing to provide a
    Prophet-compatible interface (for the rest of the pipeline).
    """

    def __init__(self):
        self.model = None
        self.fitted = None
        self.train_df = None

    def fit(self, train_df):
        self.train_df = train_df.copy()
        y = train_df.set_index("ds")["y"].asfreq("D")
        y = y.ffill().fillna(0)

        # Holt-Winters with weekly seasonality (period=7)
        self.model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="add",
            seasonal_periods=7,
            damped_trend=True,
            initialization_method="estimated",
        )
        self.fitted = self.model.fit(optimized=True)
        return self

    def predict(self, future_df):
        """Generate predictions in Prophet-compatible format."""
        last_train_date = self.train_df["ds"].max()
        all_dates = future_df["ds"].reset_index(drop=True)

        # Get fitted values for historical period
        fitted_values = self.fitted.fittedvalues

        # Count future periods
        future_mask = all_dates > last_train_date
        n_future = future_mask.sum()

        # Forecast future periods
        if n_future > 0:
            forecast_values = self.fitted.forecast(n_future)
            forecast_values = forecast_values.values
        else:
            forecast_values = np.array([])

        # Build yhat by iterating over all dates
        yhat = []
        future_idx = 0
        for date in all_dates:
            if date <= last_train_date:
                if date in fitted_values.index:
                    yhat.append(float(fitted_values.loc[date]))
                else:
                    yhat.append(np.nan)
            else:
                if future_idx < len(forecast_values):
                    yhat.append(float(forecast_values[future_idx]))
                    future_idx += 1
                else:
                    yhat.append(np.nan)

        # Build result DataFrame
        result = pd.DataFrame({"ds": all_dates})
        result["yhat"] = yhat

        # Prediction intervals (approximate: +/-1.28 * residual_std for 80% CI)
        residuals = self.fitted.resid
        resid_std = residuals.std()
        result["yhat_lower"] = result["yhat"] - 1.28 * resid_std
        result["yhat_upper"] = result["yhat"] + 1.28 * resid_std

        # Placeholder components
        result["trend"] = result["yhat"]
        result["weekly"] = 0.0
        result["yearly"] = 0.0

        return result

    def make_future_dataframe(self, periods, freq="D"):
        """Create future dates DataFrame (Prophet-compatible API)."""
        train_dates = self.train_df["ds"].sort_values().reset_index(drop=True)
        last_date = train_dates.iloc[-1]
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(days=1),
            periods=periods,
            freq=freq,
        )
        all_dates = pd.concat([train_dates, pd.Series(future_dates)], ignore_index=True)
        return pd.DataFrame({"ds": all_dates})

    def plot_components(self, forecast):
        """Generate a simple component plot."""
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(12, 10))

        axes[0].plot(forecast["ds"], forecast["yhat"], color="blue")
        axes[0].set_title("Trend (Fitted Values)")
        axes[0].set_ylabel("Units")

        forecast_copy = forecast.copy()
        forecast_copy["dow"] = forecast_copy["ds"].dt.dayofweek
        weekly = forecast_copy.groupby("dow")["yhat"].mean()
        axes[1].bar(range(7), weekly.values, color="steelblue")
        axes[1].set_xticks(range(7))
        axes[1].set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        axes[1].set_title("Weekly Pattern")
        axes[1].set_ylabel("Avg Units")

        forecast_copy["month"] = forecast_copy["ds"].dt.month
        monthly = forecast_copy.groupby("month")["yhat"].mean()
        axes[2].bar(range(1, 13), monthly.values, color="coral")
        axes[2].set_title("Monthly Pattern")
        axes[2].set_xlabel("Month")
        axes[2].set_ylabel("Avg Units")

        plt.tight_layout()
        return fig


def train_holtwinters(drug_name, train_df, forecast_periods):
    """Train using Holt-Winters and return forecast DataFrame."""
    model = HoltWintersWrapper()
    model.fit(train_df)

    future = model.make_future_dataframe(periods=forecast_periods)
    forecast = model.predict(future)

    return model, forecast


# =============================================================================
# UNIFIED TRAINING INTERFACE
# =============================================================================
def train_single_drug(
    drug_name: str,
    df: pd.DataFrame,
    holidays_df: pd.DataFrame,
    models_dir: str = "models",
    drug_catalog: dict = None,
) -> dict:
    """
    Train a forecasting model for a single drug.
    Automatically selects Prophet or Holt-Winters based on availability.
    Uses per-drug hyperparameters from config for optimal accuracy.
    """
    print(f"\n{'='*50}")
    print(f"  Training model for: {drug_name}")
    print(f"{'='*50}")

    prophet_df = prepare_prophet_data(df, drug_name)
    train_df, test_df = train_test_split(prophet_df)

    forecast_periods = len(test_df) + FORECAST_HORIZON_DAYS

    posterior_samples = None

    if PROPHET_AVAILABLE:
        catalog = drug_catalog or DRUG_CATALOG
        drug_config = catalog[drug_name]
        print(f"  Using: Facebook Prophet (tuned)")
        print(f"    changepoint_prior: {drug_config.get('changepoint_prior_scale', 0.05)}")
        print(f"    seasonality_prior: {drug_config.get('seasonality_prior_scale', 10.0)}")
        model, forecast, posterior_samples = train_prophet(drug_name, train_df, holidays_df, forecast_periods, drug_config=drug_config)
    else:
        print("  Using: Holt-Winters Exponential Smoothing")
        model, forecast = train_holtwinters(drug_name, train_df, forecast_periods)

    # Save model
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, f"{drug_name}_model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Model saved: {model_path}")

    return {
        "drug_name": drug_name,
        "model": model,
        "train_df": train_df,
        "test_df": test_df,
        "forecast": forecast,
        "posterior_samples": posterior_samples,
    }


def train_all_drugs(save_dir: str = "models", drug_catalog: dict = None, data: pd.DataFrame = None) -> dict:
    """Train models for all drugs in the catalog (or a custom catalog)."""
    df = data if data is not None else load_data()
    holidays_df = create_holiday_dataframe()
    catalog = drug_catalog or DRUG_CATALOG

    results = {}
    for drug_name in catalog.keys():
        result = train_single_drug(drug_name, df, holidays_df, save_dir, drug_catalog=catalog)
        results[drug_name] = result

    backend = "Prophet" if PROPHET_AVAILABLE else "Holt-Winters"
    print("\n" + "=" * 50)
    print(f"  ALL MODELS TRAINED SUCCESSFULLY (backend: {backend})")
    print("=" * 50)

    return results


def load_trained_model(drug_name: str, models_dir: str = "models"):
    """Load a previously trained model from disk."""
    model_path = os.path.join(models_dir, f"{drug_name}_model.pkl")
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    return model


if __name__ == "__main__":
    results = train_all_drugs()

    for drug_name, result in results.items():
        forecast = result["forecast"]
        last_30 = forecast.tail(FORECAST_HORIZON_DAYS)[["ds", "yhat", "yhat_lower", "yhat_upper"]]
        print(f"\n  {drug_name} - Next {FORECAST_HORIZON_DAYS} Day Forecast (preview):")
        print(last_30.head(5).to_string(index=False))
        print("  ...")
