"""
run_pipeline.py - Main Pipeline Orchestrator

Runs the complete ETL + Inference pipeline end-to-end:
  1. Generate synthetic pharmacy sales data
  2. Preprocess and generate EDA visualizations
  3. Train Prophet models for all drugs
  4. Evaluate models and calculate MAPE
  5. Generate reorder recommendations

Usage:
    python run_pipeline.py

This is the single entry point that runs everything.
"""

import os
import sys
import time
from datetime import datetime

# Pipeline modules
from data_generator import generate_all_data, save_data
from data_preprocessing import load_data, generate_eda_plots
from model_training import train_all_drugs
from model_evaluation import evaluate_single_drug, generate_evaluation_plots
from decision_engine import generate_reorder_recommendations, generate_inventory_simulation_plot


def print_banner(step: int, title: str):
    """Print a formatted step banner."""
    print(f"\n{'#' * 70}")
    print(f"#  STEP {step}: {title}")
    print(f"{'#' * 70}\n")


def main():
    """Execute the full pipeline."""
    start_time = time.time()

    print("\n" + "=" * 70)
    print("  INTELLIGENT PHARMACY INVENTORY MANAGEMENT SYSTEM")
    print("  Time-Series Forecasting Pipeline")
    print(f"  Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Ensure output directory exists
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    os.makedirs("models", exist_ok=True)

    # =========================================================================
    # STEP 1: DATA GENERATION
    # =========================================================================
    print_banner(1, "SYNTHETIC DATA GENERATION")
    df = generate_all_data()
    save_data(df)

    # =========================================================================
    # STEP 2: EXPLORATORY DATA ANALYSIS
    # =========================================================================
    print_banner(2, "EXPLORATORY DATA ANALYSIS")
    df = load_data()
    generate_eda_plots(df)

    # =========================================================================
    # STEP 3: MODEL TRAINING
    # =========================================================================
    print_banner(3, "PROPHET MODEL TRAINING")
    results = train_all_drugs()

    # =========================================================================
    # STEP 4: MODEL EVALUATION
    # =========================================================================
    print_banner(4, "MODEL EVALUATION")
    print("  EVALUATION METRICS (Test Set):")
    print("-" * 80)

    all_metrics = []
    for drug_name, result in results.items():
        metrics = evaluate_single_drug(result)
        all_metrics.append(metrics)

    import pandas as pd
    metrics_df = pd.DataFrame(all_metrics)

    print("-" * 80)
    avg_mape = metrics_df["mape"].mean()
    pass_count = metrics_df["target_met"].sum()
    print(f"\n  Average MAPE: {avg_mape:.2f}%")
    print(f"  Models meeting <20% target: {pass_count}/{len(metrics_df)}")

    # Generate evaluation plots
    print("\n  Generating evaluation plots...")
    generate_evaluation_plots(results)
    metrics_df.to_csv("outputs/evaluation_metrics.csv", index=False)

    # =========================================================================
    # STEP 5: REORDER RECOMMENDATIONS
    # =========================================================================
    print_banner(5, "REORDER RECOMMENDATIONS")
    rec_df = generate_reorder_recommendations(results)
    rec_df.to_csv("outputs/reorder_recommendations.csv", index=False)

    # Generate inventory simulation
    generate_inventory_simulation_plot(results)

    # =========================================================================
    # PIPELINE COMPLETE
    # =========================================================================
    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETE!")
    print(f"  Total runtime: {elapsed:.1f} seconds")
    print(f"  Outputs saved to: ./outputs/")
    print("  Files generated:")
    for f in sorted(os.listdir("outputs")):
        size = os.path.getsize(os.path.join("outputs", f))
        print(f"    - {f} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
