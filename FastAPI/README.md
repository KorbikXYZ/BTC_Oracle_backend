## API Local Development & Production Deployment

### 1. Running the Server Locally
To start the FastAPI service for local development or debugging, activate the virtual environment and initialize Uvicorn with auto-reload:

```bash
# Activate the virtual environment
source .venv_docker/bin/activate

# Launch the API server with live code reloading
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Production Deployment Configurations
* **Development Mode (`--reload`):** Monitored code changes and automatically restarted the server. Restricted to 1 worker thread (not suitable for live traffic).
* **Production Mode (`--workers 4`):** Leveraged a multi-process architecture by spawning 4 independent worker processes to distribute client load and maximize throughput.

```bash
# Recommended command for live production environments
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3. Live Production Widget Routings
The micro-service securely routes individual frontend requests to specific aggregated database views. Valid target parameters for the `/api/v1/widget/{widget_id}` endpoint include:
* `current_btc_price_fng_heatmap`
* `current_btc_rolling_z_score_1460d`
* `current_btc_global_onchain_mvrv`
* `current_btc_power_law_price_trend`
* `current_btc_power_law_deviation_oscillator`
* `current_btc_power_law_multi_horizons`
