"""
model_evaluation.py - Model Evaluation & Backtesting

Evaluates Prophet models using:
  - Mean Absolute Percentage Error (MAPE) - primary metric per proposal
  - Mean Absolute Error (MAE)
  - Root Mean Squared Error (RMSE)
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
from prophet.diagnostics import cross_validation, performance_metrics
from prophet.plot import plot_cross_validation_metric

from config import DRUG_CATALOG, FORECAST_HORIZON_DAYS
from data_preprocessing import load_data, prepare_prophet_data, create_holiday_dataframe, train_test_split
from model_training import train_all_drugs


def calculate_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Calculate Mean Absolute Percentage Error.

    Filters out zero actuals to avoid division by zero.
    """
    mask = actual != 0
    if mask.sum() == 0:
        return np.nan
    return np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100


def calculate_mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Calculate Mean Absolute Error."""
    return np.mean(np.abs(actual - predicted))


def calculate_rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Calculate Root Mean Squared Error."""
    return np.sqrt(np.mean((actual - predicted) ** 2))


def evaluate_single_drug(result: dict, output_dir: str = "outputs") -> dict:
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
    mae = calculate_mae(actual, predicted)
    rmse = calculate_rmse(actual, predicted)

    metrics = {
        "drug_name": drug_name,
        "mape": round(mape, 2),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "test_days": len(merged),
        "target_met": mape < 20,
    }

    print(f"  {drug_name:<30} | MAPE: {mape:>6.2f}% | MAE: {mae:>5.2f} | RMSE: {rmse:>5.2f} | {'PASS' if mape < 20 else 'FAIL'}")

    return metrics


def generate_evaluation_plots(results: dict, output_dir: str = "outputs"):
    """
    Generate visual evaluation plots for all drugs.
    """
    os.makedirs(output_dir, exist_ok=True)
    sns.set_style("whitegrid")

    # --- Plot 1: Actual vs Predicted for Each Drug ---
    n_drugs = len(results)
    fig, axes = plt.subplots(4, 2, figsize=(16, 16))
    fig.suptitle("Model Evaluation: Actual vs Predicted (Test Set)", fontsize=16, fontweight="bold")

    for idx, (drug_name, result) in enumerate(results.items()):
        ax = axes[idx // 2, idx % 2]
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

        mape = calculate_mape(merged["y"].values, np.clip(merged["yhat"].values, 0, None))
        ax.set_title(f"{drug_name.replace('_', ' ')} (MAPE: {mape:.1f}%)", fontsize=11)
        ax.legend(fontsize=8)
        ax.set_ylabel("Units Sold")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "eval_actual_vs_predicted.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved: {output_dir}/eval_actual_vs_predicted.png")

    # --- Plot 2: Prophet Component Decomposition (one example drug) ---
    example_drug = "Amoxicillin_500mg"
    result = results[example_drug]
    model = result["model"]
    forecast = result["forecast"]

    fig = model.plot_components(forecast)
    fig.suptitle(f"Prophet Components: {example_drug}", fontsize=14, fontweight="bold", y=1.02)
    fig.savefig(os.path.join(output_dir, "eval_components_amoxicillin.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_dir}/eval_components_amoxicillin.png")

    # --- Plot 3: MAPE Summary Bar Chart ---
    all_metrics = []
    for drug_name, result in results.items():
        metrics = evaluate_single_drug(result, output_dir)
        all_metrics.append(metrics)

    metrics_df = pd.DataFrame(all_metrics)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["#2ecc71" if m else "#e74c3c" for m in metrics_df["target_met"]]
    bars = ax.barh(metrics_df["drug_name"], metrics_df["mape"], color=colors, edgecolor="white")
    ax.axvline(x=20, color="red", linestyle="--", linewidth=2, label="20% MAPE Target")
    ax.set_xlabel("MAPE (%)", fontsize=12)
    ax.set_title("Model Accuracy: MAPE by Drug (Target < 20%)", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)

    for bar, val in zip(bars, metrics_df["mape"]):
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

    # Evaluate
    print("\n  EVALUATION METRICS (Test Set):")
    print("-" * 80)

    all_metrics = []
    for drug_name, result in results.items():
        metrics = evaluate_single_drug(result)
        all_metrics.append(metrics)

    metrics_df = pd.DataFrame(all_metrics)

    print("-" * 80)
    avg_mape = metrics_df["mape"].mean()
    pass_count = metrics_df["target_met"].sum()
    print(f"\n  Average MAPE: {avg_mape:.2f}%")
    print(f"  Models meeting <20% target: {pass_count}/{len(metrics_df)}")

    # Generate plots
    print("\nGenerating evaluation plots...")
    metrics_df = generate_evaluation_plots(results)

    # Save metrics to CSV
    metrics_df.to_csv("outputs/evaluation_metrics.csv", index=False)
    print(f"\n  Metrics saved to: outputs/evaluation_metrics.csv")
