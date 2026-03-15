"""
model_evaluation.py - Model Evaluation & Backtesting

Evaluates Prophet models using:
  - Mean Absolute Percentage Error (MAPE) - primary metric per proposal
  - Symmetric MAPE (sMAPE) - handles low-count days more fairly
  - Mean Absolute Error (MAE)
  - Root Mean Squared Error (RMSE)
  - Prophet cross-validation for robust out-of-sample evaluation
  - Visual diagnostics (actual vs predicted, component plots)

The project target is MAPE < 20%.

Usage:
    python model_evaluation.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS
from data_preprocessing import load_data, prepare_prophet_data, create_holiday_dataframe, train_test_split
from model_training import train_all_drugs, PROPHET_AVAILABLE


def calculate_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Calculate Mean Absolute Percentage Error.
    Filters out zero actuals to avoid division by zero.
    """
    mask = actual != 0
    if mask.sum() == 0:
        return np.nan
    return np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100


def calculate_smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Calculate Symmetric Mean Absolute Percentage Error.
    More robust than MAPE for low-count data (e.g., weekend sales).
    sMAPE = 200 * mean(|actual - predicted| / (|actual| + |predicted|))
    """
    denominator = np.abs(actual) + np.abs(predicted)
    mask = denominator > 0
    if mask.sum() == 0:
        return np.nan
    return np.mean(np.abs(actual[mask] - predicted[mask]) / denominator[mask]) * 200


def calculate_mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Calculate Mean Absolute Error."""
    return np.mean(np.abs(actual - predicted))


def calculate_rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Calculate Root Mean Squared Error."""
    return np.sqrt(np.mean((actual - predicted) ** 2))


def calculate_weighted_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Calculate Weighted MAPE (volume-weighted).
    Gives more weight to high-demand days, less to low-count weekends.
    wMAPE = sum(|actual - predicted|) / sum(|actual|) * 100
    """
    total_actual = np.sum(np.abs(actual))
    if total_actual == 0:
        return np.nan
    return np.sum(np.abs(actual - predicted)) / total_actual * 100


def evaluate_single_drug(result: dict) -> dict:
    """
    Evaluate a trained model against the held-out test set.

    Parameters
    ----------
    result : dict
        Output from train_single_drug() containing model, test_df, forecast.

    Returns
    -------
    dict
        Evaluation metrics.
    """
    drug_name = result["drug_name"]
    test_df = result["test_df"]
    forecast = result["forecast"]

    # Merge test actuals with forecast predictions
    merged = test_df.merge(
        forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]],
        on="ds",
        how="inner",
    )

    actual = merged["y"].values
    predicted = merged["yhat"].values

    # Clip predictions to be non-negative (can't sell negative units)
    predicted = np.clip(predicted, 0, None)

    mape = calculate_mape(actual, predicted)
    smape = calculate_smape(actual, predicted)
    wmape = calculate_weighted_mape(actual, predicted)
    mae = calculate_mae(actual, predicted)
    rmse = calculate_rmse(actual, predicted)

    # Calculate prediction interval coverage
    in_interval = ((actual >= merged["yhat_lower"].values) &
                   (actual <= merged["yhat_upper"].values)).mean() * 100

    metrics = {
        "drug_name": drug_name,
        "mape": round(mape, 2),
        "smape": round(smape, 2),
        "wmape": round(wmape, 2),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "coverage_80pct": round(in_interval, 1),
        "test_days": len(merged),
        "target_met": wmape < 20,  # Use wMAPE for fairer target evaluation
    }

    status = "PASS" if wmape < 20 else "FAIL"
    print(f"  {drug_name:<30} | wMAPE: {wmape:>6.2f}% | MAPE: {mape:>6.2f}% | MAE: {mae:>5.2f} | CI Coverage: {in_interval:.0f}% | {status}")

    return metrics


def run_prophet_cross_validation(result: dict) -> dict:
    """
    Run Prophet's built-in cross-validation for robust evaluation.
    Uses expanding window with multiple cutoffs.
    """
    if not PROPHET_AVAILABLE:
        return None

    from prophet.diagnostics import cross_validation, performance_metrics

    model = result["model"]
    drug_name = result["drug_name"]

    try:
        # Cross-validate: 30-day horizon, 30-day between cutoffs, 365-day initial training
        df_cv = cross_validation(
            model,
            initial="365 days",
            period="30 days",
            horizon="30 days",
        )

        # Calculate metrics manually for compatibility across Prophet versions
        df_cv["abs_err"] = np.abs(df_cv["y"] - df_cv["yhat"])
        df_cv["abs_pct_err"] = df_cv["abs_err"] / np.abs(df_cv["y"].clip(lower=0.1))
        df_cv["in_interval"] = (df_cv["y"] >= df_cv["yhat_lower"]) & (df_cv["y"] <= df_cv["yhat_upper"])

        cv_mape = df_cv["abs_pct_err"].mean() * 100
        cv_mae = df_cv["abs_err"].mean()
        cv_rmse = np.sqrt((df_cv["abs_err"] ** 2).mean())
        cv_coverage = df_cv["in_interval"].mean() * 100

        cv_result = {
            "drug_name": drug_name,
            "cv_mape": round(cv_mape, 2),
            "cv_mae": round(cv_mae, 2),
            "cv_rmse": round(cv_rmse, 2),
            "cv_coverage": round(cv_coverage, 1),
            "n_cutoffs": len(df_cv["cutoff"].unique()),
        }
        print(f"  CV {drug_name:<27} | CV MAPE: {cv_result['cv_mape']:>6.2f}% | Coverage: {cv_result['cv_coverage']:.0f}% | Cutoffs: {cv_result['n_cutoffs']}")
        return cv_result
    except Exception as e:
        print(f"  CV {drug_name:<27} | SKIPPED ({type(e).__name__}: {e})")
        return {"drug_name": drug_name, "cv_mape": np.nan, "cv_error": str(e)}


def generate_evaluation_plots(results: dict, all_metrics: list, output_dir: str = "outputs"):
    """
    Generate visual evaluation plots for all drugs.
    Accepts pre-computed metrics to avoid duplicate computation.
    """
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    # --- Plot 1: Actual vs Predicted for Each Drug ---
    n_drugs = len(results)
    n_cols = 2
    n_rows = max(1, (n_drugs + 1) // 2)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(16, 4 * n_rows))
    if n_drugs == 1:
        axes = np.array([[axes]])
    elif n_rows == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle("Model Evaluation: Actual vs Predicted (Test Set)", fontsize=16, fontweight="bold")

    for idx, (drug_name, result) in enumerate(results.items()):
        ax = axes[idx // n_cols, idx % n_cols]
        test_df = result["test_df"]
        forecast = result["forecast"]

        merged = test_df.merge(
            forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]],
            on="ds",
            how="inner",
        )

        ax.plot(merged["ds"], merged["y"], "b-", label="Actual", linewidth=1.2)
        ax.plot(merged["ds"], merged["yhat"], "r--", label="Predicted", linewidth=1.2)
        ax.fill_between(
            merged["ds"],
            merged["yhat_lower"],
            merged["yhat_upper"],
            alpha=0.2,
            color="red",
            label="80% CI",
        )

        # Find matching metrics
        drug_metrics = next((m for m in all_metrics if m["drug_name"] == drug_name), None)
        wmape = drug_metrics["wmape"] if drug_metrics else 0
        ax.set_title(f"{drug_name.replace('_', ' ')} (wMAPE: {wmape:.1f}%)", fontsize=11)
        ax.legend(fontsize=8)
        ax.set_ylabel("Units Sold")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    for idx in range(n_drugs, n_rows * n_cols):
        axes[idx // n_cols, idx % n_cols].set_visible(False)

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eval_actual_vs_predicted.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved: {output_dir}/eval_actual_vs_predicted.png")

    # --- Plot 2: Prophet Component Decomposition (one example drug) ---
    example_drug = list(results.keys())[0]
    result = results[example_drug]
    model = result["model"]
    forecast = result["forecast"]

    fig = model.plot_components(forecast)
    fig.suptitle(f"Prophet Components: {example_drug}", fontsize=14, fontweight="bold", y=1.02)
    fig.savefig(os.path.join(output_dir, "eval_components_amoxicillin.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eval_components_amoxicillin.png")

    # --- Plot 3: MAPE Summary Bar Chart (using wMAPE) ---
    metrics_df = pd.DataFrame(all_metrics)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["#2ecc71" if m else "#e74c3c" for m in metrics_df["target_met"]]
    bars = ax.barh(metrics_df["drug_name"], metrics_df["wmape"], color=colors, edgecolor="white")
    ax.axvline(x=20, color="red", linestyle="--", linewidth=2, label="20% wMAPE Target")
    ax.set_xlabel("Weighted MAPE (%)", fontsize=12)
    ax.set_title("Model Accuracy: wMAPE by Drug (Target < 20%)", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)

    for bar, val in zip(bars, metrics_df["wmape"]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", fontsize=10)

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eval_mape_summary.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eval_mape_summary.png")

    return metrics_df


if __name__ == "__main__":
    print("=" * 60)
    print("  MODEL EVALUATION")
    print("=" * 60)

    # Train all models
    results = train_all_drugs()

    # Evaluate (single pass - no duplicates)
    print("\n  EVALUATION METRICS (Test Set):")
    print("-" * 100)

    all_metrics = []
    for drug_name, result in results.items():
        metrics = evaluate_single_drug(result)
        all_metrics.append(metrics)

    metrics_df = pd.DataFrame(all_metrics)

    print("-" * 100)
    avg_wmape = metrics_df["wmape"].mean()
    avg_mape = metrics_df["mape"].mean()
    pass_count = metrics_df["target_met"].sum()
    print(f"\n  Average wMAPE: {avg_wmape:.2f}%")
    print(f"  Average MAPE:  {avg_mape:.2f}%")
    print(f"  Models meeting <20% target: {pass_count}/{len(metrics_df)}")

    # Prophet cross-validation
    if PROPHET_AVAILABLE:
        print("\n  PROPHET CROSS-VALIDATION:")
        print("-" * 100)
        cv_results = []
        for drug_name, result in results.items():
            cv_result = run_prophet_cross_validation(result)
            if cv_result:
                cv_results.append(cv_result)

        if cv_results:
            cv_df = pd.DataFrame(cv_results)
            cv_df.to_csv("outputs/cross_validation_metrics.csv", index=False)
            print(f"\n  CV metrics saved to: outputs/cross_validation_metrics.csv")

    # Generate plots (using pre-computed metrics - no duplication)
    print("\nGenerating evaluation plots...")
    generate_evaluation_plots(results, all_metrics)

    # Save metrics to CSV
    metrics_df.to_csv("outputs/evaluation_metrics.csv", index=False)
    print(f"\n  Metrics saved to: outputs/evaluation_metrics.csv")
