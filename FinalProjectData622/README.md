# 💊 Intelligent Pharmacy Inventory Management System
### Minimizing Waste and Preventing Stockouts via Time-Series Forecasting

**Group X** — Umais Siddiqui et al.

---

## 📋 Overview

A Machine Learning-driven inventory system for community pharmacies that uses **Facebook Prophet** (additive regression model) to forecast medication demand and generate actionable reorder recommendations. Solves the "Optimization Paradox": balancing high stock levels for patient safety against minimizing waste from expired medications.

---

## 🗂️ Project Structure

```
pharmacy_inventory/
├── config.py                 # Central configuration (drug catalog, parameters)
├── data_generator.py         # Synthetic data engine (Objective A)
├── data_preprocessing.py     # Data cleaning, EDA, Prophet formatting
├── model_training.py         # Prophet model training (Objective B)
├── model_evaluation.py       # MAPE/MAE/RMSE evaluation & plots
├── decision_engine.py        # Reorder recommendations (Objective C)
├── run_pipeline.py           # ⭐ Main entry point — runs everything
├── dashboard.py              # Streamlit interactive dashboard
├── requirements.txt          # Python dependencies
├── data/                     # Generated sales data (CSV)
├── models/                   # Trained Prophet models (pickle)
└── outputs/                  # Evaluation plots, metrics, recommendations
```

---

## 🚀 How to Run

### Prerequisites
- Python 3.9 or higher
- pip (Python package manager)

### Step 1: Install Dependencies

```bash
cd pharmacy_inventory
pip install -r requirements.txt or uv add -r requirements.txt 
uv python pin 3.12
uv sync
```

> **Note**: Prophet may require additional system dependencies. If you get errors:
> - **Mac**: `brew install pystan`
> - **Windows**: Install via `conda install -c conda-forge prophet`
> - **Linux**: `pip install prophet` should work directly

### Step 2: Run the Full Pipeline

```bash
python run_pipeline.py
```

This single command executes the entire ETL + Inference pipeline:

1. **Generates** 2 years of synthetic pharmacy sales data (8 drugs × 731 days = 5,848 records)
2. **Creates** EDA visualizations (time series, heatmaps, day-of-week patterns)
3. **Trains** Prophet forecasting models for each drug
4. **Evaluates** models against held-out test data (targeting MAPE < 20%)
5. **Generates** reorder recommendations with urgency levels
6. **Produces** inventory simulation plots

### Step 3: Launch the Interactive Dashboard (Optional)

```bash
streamlit run dashboard.py
```

Opens a web dashboard at `http://localhost:8501` with:
- Real-time inventory overview & KPIs
- Interactive 30-day demand forecasts per drug
- Reorder alert details with stock depletion simulation
- EDA explorer with drug comparisons

---

## 🔬 Running Individual Modules

You can also run each step independently:

```bash
# Step 1: Generate synthetic data only
python data_generator.py

# Step 2: Run EDA and preprocessing only
python data_preprocessing.py

# Step 3: Train models only
python model_training.py

# Step 4: Evaluate models only (trains first if needed)
python model_evaluation.py

# Step 5: Generate reorder recommendations only
python decision_engine.py
```

---

## 📊 Output Files

After running the pipeline, check the `outputs/` folder:

| File | Description |
|------|-------------|
| `eda_daily_sales.png` | Time series plots for all 8 drugs |
| `eda_monthly_heatmap.png` | Monthly sales heatmap |
| `eda_day_of_week.png` | Day-of-week distribution boxplots |
| `eval_actual_vs_predicted.png` | Actual vs. Predicted for test set |
| `eval_components_amoxicillin.png` | Prophet decomposition (trend + seasonality) |
| `eval_mape_summary.png` | MAPE bar chart with 20% target line |
| `inventory_simulation.png` | 30-day stock depletion projections |
| `evaluation_metrics.csv` | MAPE, MAE, RMSE per drug |
| `reorder_recommendations.csv` | Order quantities, costs, urgency levels |

---

## 💊 Drug Catalog

| Drug | Category | Seasonal Profile | Base Demand |
|------|----------|-----------------|-------------|
| Amoxicillin 500mg | Antibiotic | Winter spike (flu) | 18/day |
| Metformin 500mg | Diabetes | Stable (chronic) | 30/day |
| Lisinopril 10mg | Blood Pressure | Stable (chronic) | 25/day |
| Albuterol Inhaler | Respiratory | Winter spike | 8/day |
| Cetirizine 10mg | Allergy | Spring spike | 12/day |
| Azithromycin 250mg | Antibiotic | Winter spike | 10/day |
| Omeprazole 20mg | Gastrointestinal | Holiday spike | 20/day |
| Sertraline 50mg | Mental Health | Winter SAD | 15/day |

---

## 🧠 Technical Details

### Data Generation
- Synthetic engine models: yearly seasonality, weekly patterns (weekend dip), long-term trend, holiday effects, and Poisson noise
- Calibrated against CDC FluView seasonal curves and general prescription volume patterns
- HIPAA-compliant by design (no real patient data)

### Model
- **Facebook Prophet** — additive regression model with:
  - Linear trend with automatic changepoint detection
  - Yearly, weekly, and monthly Fourier seasonality
  - US holiday regressors
  - 80% prediction intervals

### Evaluation
- Primary metric: **MAPE** (Mean Absolute Percentage Error), target < 20%
- Secondary: MAE, RMSE
- Walk-forward validation on last 60 days of data

### Decision Engine
- Reorder Point = (Lead Time × Avg Demand) + (Safety Stock Days × Avg Demand)
- Conservative ordering using 80th percentile forecast
- 4-tier urgency system: CRITICAL → HIGH → MEDIUM → LOW

---

## 🔧 Configuration

Edit `config.py` to customize:
- Add/remove drugs from `DRUG_CATALOG`
- Adjust seasonal profiles in `SEASONAL_PROFILES`
- Change simulation dates, forecast horizon, or business rules
- Tune model parameters (changepoint prior, seasonality strength)

---

## 📚 Data Sources for Calibration

While this project uses synthetic data, the simulation parameters are calibrated against:
- **CDC FluView** — Seasonal flu timing and intensity
- **CMS Drug Utilization Data** — Prescription volume baselines
- **US Holiday Calendar** — via Python `holidays` library
- **General pharmacy operations knowledge** — Weekend hours, lead times

---

## 📝 License

Academic project — Group X, 2026.
