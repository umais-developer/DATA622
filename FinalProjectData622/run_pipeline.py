"""
run_pipeline.py - Main Pipeline Orchestrator

Runs the complete ETL + Inference pipeline end-to-end:
  1. Generate synthetic pharmacy sales data (2024-2026)
  2. Preprocess and generate EDA visualizations
  3. Train Prophet models for all drugs (with per-drug tuning)
  4. Evaluate models (MAPE, sMAPE, wMAPE, cross-validation)
  5. Generate reorder recommendations with cost analysis
  6. Produce wastage vs understocking economic analysis

Usage:
    python run_pipeline.py

This is the single entry point that runs everything.
"""

import os
import sys
import time
import pandas as pd
from datetime import datetime

# Pipeline modules
from data_adapter import load_yaml_config, is_synthetic_mode, get_pharmacy_name
from data_preprocessing import load_data, generate_eda_plots
from model_training import train_all_drugs, PROPHET_AVAILABLE
from model_evaluation import (
    evaluate_single_drug,
    generate_evaluation_plots,
    run_prophet_cross_validation,
)
from decision_engine import (
    generate_reorder_recommendations,
    generate_inventory_simulation_plot,
    generate_cost_analysis_plot,
)
from config import DATA_DIR, MODELS_DIR, OUTPUTS_DIR


def run_pipeline_steps(
    drug_catalog: dict = None,
    data: pd.DataFrame = None,
    progress_callback=None,
):
    """
    Run the full pipeline with optional progress callbacks.
    Used by the dashboard upload feature.

    Returns dict with keys: results, metrics_df, rec_df, elapsed
    """
    start_time = time.time()

    def report(step, total, msg):
        if progress_callback:
            progress_callback(step, total, msg)
        print(msg)

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)

    # Step 1: Load data
    report(1, 5, "Loading and validating data...")
    if data is None:
        data = load_data()

    # Step 2: EDA
    report(2, 5, "Generating exploratory analysis...")
    generate_eda_plots(data)

    # Step 3: Train models
    report(3, 5, "Training forecasting models...")
    results = train_all_drugs(
        save_dir=MODELS_DIR,
        drug_catalog=drug_catalog,
        data=data,
    )

    # Step 4: Evaluate
    report(4, 5, "Evaluating model accuracy...")
    all_metrics = []
    for drug_name, result in results.items():
        metrics = evaluate_single_drug(result)
        all_metrics.append(metrics)

    metrics_df = pd.DataFrame(all_metrics)

    if PROPHET_AVAILABLE:
        cv_results = []
        for drug_name, result in results.items():
            cv_result = run_prophet_cross_validation(result)
            if cv_result:
                cv_results.append(cv_result)
        if cv_results:
            cv_df = pd.DataFrame(cv_results)
            cv_df.to_csv(os.path.join(OUTPUTS_DIR, "cross_validation_metrics.csv"), index=False)

    generate_evaluation_plots(results, all_metrics)
    metrics_df.to_csv(os.path.join(OUTPUTS_DIR, "evaluation_metrics.csv"), index=False)

    # Step 5: Recommendations
    report(5, 5, "Generating reorder recommendations...")
    rec_df = generate_reorder_recommendations(results, drug_catalog=drug_catalog)
    rec_df.to_csv(os.path.join(OUTPUTS_DIR, "reorder_recommendations.csv"), index=False)
    generate_inventory_simulation_plot(results, drug_catalog=drug_catalog)
    generate_cost_analysis_plot(rec_df)

    elapsed = time.time() - start_time

    return {
        "results": results,
        "metrics_df": metrics_df,
        "rec_df": rec_df,
        "elapsed": elapsed,
    }


def print_banner(step: int, title: str):
    """Print a formatted step banner."""
    print(f"\n{'#' * 70}")
    print(f"#  STEP {step}: {title}")
    print(f"{'#' * 70}\n")


def main():
    """Execute the full pipeline."""
    start_time = time.time()

    config = load_yaml_config()
    synthetic = is_synthetic_mode(config)
    pharmacy = get_pharmacy_name(config)
    mode_label = "SYNTHETIC DATA" if synthetic else f"REAL DATA ({pharmacy})"

    print("\n" + "=" * 70)
    print("  INTELLIGENT PHARMACY INVENTORY MANAGEMENT SYSTEM")
    print("  Time-Series Forecasting Pipeline")
    print("  With Wastage & Understocking Cost Analysis")
    print(f"  Mode: {mode_label}")
    print(f"  Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Ensure output directories exist
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)

    # =========================================================================
    # STEP 1: DATA GENERATION OR LOADING
    # =========================================================================
    if synthetic:
        print_banner(1, "SYNTHETIC DATA GENERATION (2024-2026)")
        from data_generator import generate_all_data, save_data
        df = generate_all_data()
        save_data(df)
    else:
        print_banner(1, f"LOADING REAL DATA ({pharmacy})")
        print("  Skipping synthetic data generation.")
        print("  Loading real pharmacy data from configured CSV...")

    # =========================================================================
    # STEP 2: EXPLORATORY DATA ANALYSIS
    # =========================================================================
    print_banner(2, "EXPLORATORY DATA ANALYSIS")
    df = load_data()
    generate_eda_plots(df)

    # =========================================================================
    # STEP 3: MODEL TRAINING (Per-Drug Tuned Hyperparameters)
    # =========================================================================
    print_banner(3, "PROPHET MODEL TRAINING (Tuned Per Drug)")
    results = train_all_drugs()

    # =========================================================================
    # STEP 4: MODEL EVALUATION
    # =========================================================================
    print_banner(4, "MODEL EVALUATION")
    print("  EVALUATION METRICS (Test Set):")
    print("-" * 100)

    # Single pass evaluation (no duplicates)
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
            cv_df.to_csv(os.path.join(OUTPUTS_DIR, "cross_validation_metrics.csv"), index=False)

    # Generate evaluation plots (pass pre-computed metrics)
    print("\n  Generating evaluation plots...")
    generate_evaluation_plots(results, all_metrics)
    metrics_df.to_csv(os.path.join(OUTPUTS_DIR, "evaluation_metrics.csv"), index=False)

    # =========================================================================
    # STEP 5: REORDER RECOMMENDATIONS WITH COST ANALYSIS
    # =========================================================================
    print_banner(5, "REORDER RECOMMENDATIONS & COST ANALYSIS")
    rec_df = generate_reorder_recommendations(results)
    rec_df.to_csv(os.path.join(OUTPUTS_DIR, "reorder_recommendations.csv"), index=False)

    # Generate inventory simulation and cost analysis plots
    generate_inventory_simulation_plot(results)
    generate_cost_analysis_plot(rec_df)

    # =========================================================================
    # PIPELINE COMPLETE
    # =========================================================================
    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETE!")
    print(f"  Total runtime: {elapsed:.1f} seconds")
    print(f"  Outputs saved to: ./{OUTPUTS_DIR}/")
    print("  Files generated:")
    for f in sorted(os.listdir(OUTPUTS_DIR)):
        size = os.path.getsize(os.path.join(OUTPUTS_DIR, f))
        print(f"    - {f} ({size:,} bytes)")
    print("=" * 70)
    print("\n  To launch the interactive dashboard:")
    print("    streamlit run dashboard.py")
    print("=" * 70)


if __name__ == "__main__":
    main()
