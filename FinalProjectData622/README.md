# Intelligent Pharmacy Inventory Management System
### Minimizing Waste and Preventing Stockouts via Time-Series Forecasting

**Group X** — Umais Siddiqui et al.

---

## Overview

A Machine Learning-driven inventory system for community pharmacies that uses **Facebook Prophet** to forecast medication demand and generate actionable reorder recommendations with **full cost analysis for wastage and understocking**. Solves the "Optimization Paradox": balancing high stock levels for patient safety against minimizing waste from expired medications.

**Key Features:**
- 2024-2026 demand forecasting with per-drug tuned Prophet models
- Wastage & understocking cost functions (Total Cost of Ownership analysis)
- Inventory simulation with shelf-life expiration tracking
- Interactive Streamlit dashboard with 5 analysis pages
- Production-ready: supports real pharmacy data via CSV + Azure deployment

---

## Project Structure

```
FinalProjectData622/
├── config.py                 # Central configuration (drug catalog, cost params)
├── data_generator.py         # Synthetic data engine (Objective A)
├── data_preprocessing.py     # Data cleaning, EDA, Prophet formatting
├── model_training.py         # Prophet model training with per-drug tuning (Objective B)
├── model_evaluation.py       # wMAPE/sMAPE/MAPE evaluation + cross-validation
├── decision_engine.py        # Reorder recommendations + cost analysis (Objective C)
├── data_adapter.py           # Production data loading & validation layer
├── run_pipeline.py           # Main entry point — runs everything
├── dashboard.py              # Streamlit interactive dashboard (5 pages)
├── main.py                   # Alias entry point
├── pharmacy_config.yaml      # Pharmacist-editable configuration (no code changes)
├── Dockerfile                # Azure/Docker deployment
├── .streamlit/config.toml    # Streamlit server settings
├── requirements.txt          # Python dependencies
├── data/                     # Sales data (CSV)
│   └── sample_format.csv     # Example CSV format for real data
├── models/                   # Trained Prophet models (pickle)
└── outputs/                  # Evaluation plots, metrics, recommendations
```

---

## Quick Start

### Prerequisites
- Python 3.11+ (3.12 recommended)
- uv package manager (or pip)

### Step 1: Install Dependencies

```bash
cd FinalProjectData622
uv sync
```

Or with pip:
```bash
pip install -r requirements.txt
```

### Step 2: Run the Full Pipeline

```bash
python run_pipeline.py
```

This executes the entire pipeline:
1. **Generates** ~2 years of synthetic pharmacy sales data (8 drugs x 788 days)
2. **Creates** EDA visualizations (time series, heatmaps, day-of-week patterns)
3. **Trains** Prophet forecasting models with per-drug tuned hyperparameters
4. **Evaluates** models (wMAPE, MAPE, sMAPE, Prophet cross-validation)
5. **Generates** reorder recommendations with wastage & understocking cost analysis
6. **Produces** inventory simulation and cost analysis plots

### Step 3: Launch the Interactive Dashboard

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501` with 5 pages:
- **Dashboard** — KPIs, reorder table, cost summary, model performance
- **Forecasts** — 30-day demand forecast per drug with confidence intervals
- **Reorder Alerts** — Per-drug inventory simulation and cost breakdown
- **Cost Analysis** — Wastage vs understocking TCO, service level vs waste rate
- **EDA Explorer** — Interactive historical sales exploration

---

## Using Your Real Pharmacy Data

To switch from synthetic demo data to your actual pharmacy sales:

### Step 1: Prepare Your CSV

Export daily sales from your pharmacy system in this format:

```csv
date,drug_name,units_sold,category
2024-01-15,Amoxicillin_500mg,22,Antibiotic
2024-01-15,Metformin_500mg,31,Diabetes
2024-01-16,Amoxicillin_500mg,18,Antibiotic
...
```

See `data/sample_format.csv` for a complete example. Requirements:
- **date**: YYYY-MM-DD format
- **drug_name**: Consistent drug names (underscores for spaces)
- **units_sold**: Non-negative integer
- **category**: Drug category (e.g., Antibiotic, Diabetes)
- **Minimum**: 90 days of data (365+ days recommended for yearly seasonality)

### Step 2: Place Your CSV

Copy your CSV to `data/pharmacy_sales.csv` (replacing the synthetic file).

### Step 3: Edit Configuration

Open `pharmacy_config.yaml` and change:

```yaml
pharmacy_name: "My Downtown Pharmacy"
use_synthetic_data: false
```

### Step 4: Run the Pipeline

```bash
python run_pipeline.py
streamlit run dashboard.py
```

The system will automatically:
- Validate your data format and report any issues
- Discover all drugs in your CSV
- Train Prophet models on your real sales history
- Generate forecasts and cost analysis based on your data

### Optional: Provide Current Inventory

For more accurate reorder recommendations, create `data/current_inventory.csv`:

```csv
drug_name,units_on_hand
Amoxicillin_500mg,250
Metformin_500mg,400
```

Then set in `pharmacy_config.yaml`:
```yaml
data_source:
  inventory_csv: "data/current_inventory.csv"
```

---

## Deploy to Azure

### Option A: Azure App Service with Docker (Recommended)

```bash
# 1. Login to Azure
az login

# 2. Create a resource group
az group create --name PharmaCast-RG --location eastus

# 3. Create Azure Container Registry
az acr create --resource-group PharmaCast-RG --name pharmacastregistry --sku Basic

# 4. Login to the registry
az acr login --name pharmacastregistry

# 5. Build and push Docker image
docker build -t pharmacast .
docker tag pharmacast pharmacastregistry.azurecr.io/pharmacast:latest
docker push pharmacastregistry.azurecr.io/pharmacast:latest

# 6. Create App Service plan
az appservice plan create --name PharmaCast-Plan --resource-group PharmaCast-RG \
    --is-linux --sku B1

# 7. Create the web app
az webapp create --resource-group PharmaCast-RG --plan PharmaCast-Plan \
    --name pharmacast-app \
    --deployment-container-image-name pharmacastregistry.azurecr.io/pharmacast:latest

# 8. Configure container registry credentials
az webapp config container set --name pharmacast-app --resource-group PharmaCast-RG \
    --docker-registry-server-url https://pharmacastregistry.azurecr.io
```

Your dashboard will be available at: `https://pharmacast-app.azurewebsites.net`

### Option B: Test Locally with Docker

```bash
docker build -t pharmacast .
docker run -p 8501:8501 pharmacast
# Visit http://localhost:8501
```

### Cost Estimate
| Tier | Cost | Best For |
|------|------|----------|
| Free (F1) | $0/month | Demo/portfolio |
| Basic (B1) | ~$13/month | Small pharmacy |
| Standard (S1) | ~$70/month | Production with scaling |

---

## Output Files

After running the pipeline, check the `outputs/` folder:

| File | Description |
|------|-------------|
| `eda_daily_sales.png` | Time series plots for all 8 drugs |
| `eda_monthly_heatmap.png` | Monthly sales heatmap |
| `eda_day_of_week.png` | Day-of-week distribution boxplots |
| `eval_actual_vs_predicted.png` | Actual vs. Predicted for test set |
| `eval_components_amoxicillin.png` | Prophet decomposition (trend + seasonality) |
| `eval_mape_summary.png` | wMAPE bar chart with 20% target line |
| `inventory_simulation.png` | 30-day stock depletion projections |
| `cost_analysis.png` | TCO breakdown + service level vs waste rate |
| `evaluation_metrics.csv` | wMAPE, MAPE, sMAPE, MAE, RMSE, CI coverage per drug |
| `cross_validation_metrics.csv` | Prophet cross-validation results |
| `reorder_recommendations.csv` | Orders, costs, urgency, TCO, service level, waste rate |

---

## Drug Catalog

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

## Technical Details

### Data Generation (Objective A)
- Synthetic engine: yearly seasonality, weekly patterns, long-term trend, holiday effects
- **Negative Binomial noise** (proper count data distribution, not Gaussian)
- Calibrated against CDC FluView and CMS prescription volume patterns
- HIPAA-compliant by design (no real patient data)

### Model Training (Objective B)
- **Facebook Prophet** with per-drug tuned hyperparameters:
  - `changepoint_prior_scale`: 0.01 (stable drugs) to 0.15 (seasonal drugs)
  - `seasonality_prior_scale`: 5.0 (stable) to 20.0 (highly seasonal)
  - Yearly, weekly, monthly Fourier seasonality + US holiday regressors
  - 80% prediction intervals
- Fallback: Holt-Winters Exponential Smoothing (if Prophet unavailable)

### Evaluation
- Primary: **wMAPE** (Weighted MAPE — volume-weighted, fair for low-count days)
- Additional: MAPE, sMAPE, MAE, RMSE, 80% CI coverage
- **Prophet cross-validation** with 12 rolling cutoffs (365-day initial + 30-day horizon)
- Walk-forward validation on last 60 days

### Cost Functions (per project proposal)
- **Wastage Cost**: unit cost + disposal fee for expired inventory
- **Understocking Cost**: 3x stockout penalty + 1.5x emergency order surcharge + $5 lost customer cost
- **Holding Cost**: 20% annual carrying rate (storage, insurance, capital)
- **Total Cost of Ownership (TCO)**: sum of all cost components
- **Service Level**: % of demand fulfilled (target: 95%)
- **Waste Rate**: % of inventory expired (target: <2%)

### Decision Engine (Objective C)
- Reorder Point = (Lead Time x Avg Demand) + (Safety Stock Days x Avg Demand)
- Conservative ordering using 80th percentile forecast
- FIFO inventory simulation with shelf-life expiration tracking
- 4-tier urgency: CRITICAL > HIGH > MEDIUM > LOW

---

## Configuration

### For quick changes: edit `pharmacy_config.yaml`
- Pharmacy name, data source path, synthetic vs real mode

### For advanced tuning: edit `config.py`
- Drug catalog parameters (costs, lead times, shelf life)
- Prophet hyperparameters per drug
- Seasonal profiles and weekly patterns
- Cost function parameters (stockout penalty, holding rate, etc.)
- Forecast horizon, test split size, confidence thresholds

### Environment variables (optional)
- `PHARMACAST_DATA_DIR` — override data directory (default: `data`)
- `PHARMACAST_MODELS_DIR` — override models directory (default: `models`)
- `PHARMACAST_OUTPUTS_DIR` — override outputs directory (default: `outputs`)

---

## Data Sources for Calibration

While this project uses synthetic data by default, the simulation parameters are calibrated against:
- **CDC FluView** — Seasonal flu timing and intensity
- **CMS Drug Utilization Data** — Prescription volume baselines
- **US Holiday Calendar** — via Python `holidays` library
- **General pharmacy operations knowledge** — Weekend hours, lead times

---

## License

Academic project — Group X, 2026.
