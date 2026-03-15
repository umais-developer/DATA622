FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required for Prophet's Stan/CmdStan backend
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the pipeline on first build to generate data + train models
RUN python run_pipeline.py

EXPOSE 8080

ENV PORT=8080
ENV PHARMACAST_GCS_BUCKET=""
# OAuth (leave empty to run without auth - demo mode)
ENV GOOGLE_CLIENT_ID=""
ENV GOOGLE_CLIENT_SECRET=""
ENV OAUTH_REDIRECT_URI=""

HEALTHCHECK CMD curl --fail http://localhost:${PORT}/_stcore/health || exit 1

CMD streamlit run dashboard.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true
