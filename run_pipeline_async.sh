#!/bin/bash

# printing of execution timestamp
echo "========================================================"
echo "CAS SPUSTENIA: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"

# resolution of project directory path
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"

# switching to project root directory for env access
cd "$PROJECT_DIR"

# activation of virtual environment
if [ -f "$PROJECT_DIR/.venv_docker/bin/activate" ]; then
    source "$PROJECT_DIR/.venv_docker/bin/activate"
    echo ">> Virtualne prostredie .venv_docker bolo uspesne aktivovane."
else
    echo "CHYBA: Virtualne prostredie v $PROJECT_DIR/.venv_docker/bin/activate neexistuje!"
    exit 1
fi

# creation of logs directory if missing
mkdir -p "$PROJECT_DIR/logs"

echo "========================================================"
echo ">> 1. KROK: AKTUALIZACIA PARQUET DATABAZ (PARALELNE)"
echo "========================================================"

# execution of background data fetchers with output logging
python "$PROJECT_DIR/tools/binance_fetcher.py" > "$PROJECT_DIR/logs/binance.log" 2>&1 &
PID1=$!
python "$PROJECT_DIR/tools/coinmetrics_fetcher.py" > "$PROJECT_DIR/logs/coinmetrics.log" 2>&1 &
PID2=$!
python "$PROJECT_DIR/tools/fear_and_greed_index_fetcher.py" > "$PROJECT_DIR/logs/fear_greed.log" 2>&1 &
PID3=$!
python "$PROJECT_DIR/tools/dune_fetcher.py" > "$PROJECT_DIR/logs/dune_fetcher.log" 2>&1 &
PID4=$!

echo "Stahovanie dat bezi na pozadi, cakam na dokoncenie..."

# error checking for data fetching processes
wait $PID1 || { echo "Chyba v binance_fetcher.py! Pozri logs/binance.log"; exit 1; }
wait $PID2 || { echo "Chyba v coinmetrics_fetcher.py! Pozri logs/coinmetrics.log"; exit 1; }
wait $PID3 || { echo "Chyba v fear_and_greed_index_fetcher.py! Pozri logs/fear_greed.log"; exit 1; }
wait $PID4 || { echo "Chyba v dune_fetcher.py! Pozri logs/dune_fetcher.log"; exit 1; }

echo "Vsetky fetchery uspesne dobehli."
echo ""

echo "========================================================"
echo ">> 2. KROK: MATEMATICKE ANALYZY & EXPORT (PARALELNE)"
echo "========================================================"

# execution of mvrv analysis jobs across time horizons
python "$PROJECT_DIR/execution_and_export/onchain_mvrv_analysis_and_fear_and_greed_index_calculation_and_export.py" 1460 > "$PROJECT_DIR/logs/mvrv_export_1460.log" 2>&1 &
PID4_1460=$!
python "$PROJECT_DIR/execution_and_export/onchain_mvrv_analysis_and_fear_and_greed_index_calculation_and_export.py" 365 > "$PROJECT_DIR/logs/mvrv_export_365.log" 2>&1 &
PID4_365=$!
python "$PROJECT_DIR/execution_and_export/onchain_mvrv_analysis_and_fear_and_greed_index_calculation_and_export.py" 30 > "$PROJECT_DIR/logs/mvrv_export_30.log" 2>&1 &
PID4_30=$!

# execution of additional mathematical model scripts
python "$PROJECT_DIR/execution_and_export/power-law_binance_multi_horizonts_calculation_and_export.py" > "$PROJECT_DIR/logs/powerlaw_multi.log" 2>&1 &
PID5=$!
python "$PROJECT_DIR/execution_and_export/power-law_binance_oscilator_calculation_and_export.py" > "$PROJECT_DIR/logs/powerlaw_osc.log" 2>&1 &
PID6=$!
python "$PROJECT_DIR/execution_and_export/table_historical_return.py" > "$PROJECT_DIR/logs/table_historical_return.log" 2>&1 &
PID7=$!

python "$PROJECT_DIR/execution_and_export/nupl.py" > "$PROJECT_DIR/logs/nupl.log" 2>&1 &
PIDex_nupl=$!

echo "Analyzy a exporty bezia na pozadi, cakam na dokoncenie..."

# error checking for analysis and export tasks
wait $PID4_1460 || { echo "Chyba v mvrv_analysis (1460d)! Pozri logs/mvrv_export_1460.log"; exit 1; }
wait $PID4_365  || { echo "Chyba v mvrv_analysis (365d)! Pozri logs/mvrv_export_365.log"; exit 1; }
wait $PID4_30   || { echo "Chyba v mvrv_analysis (30d)! Pozri logs/mvrv_export_30.log"; exit 1; }
wait $PID5      || { echo "Chyba v power-law...multi...py! Pozri logs/powerlaw_multi.log"; exit 1; }
wait $PID6      || { echo "Chyba v power-law...oscilator...py! Pozri logs/powerlaw_osc.log"; exit 1; }
wait $PID7      || { echo "Chyba v table_historical_return.py! Pozri logs/table_historical_return.log"; exit 1; }

wait $PIDex_nupl      || { echo "Chyba v nupl.py! Pozri logs/nupl.log"; exit 1; }

echo ""
echo "========================================================"
echo ">> PIPELINE BOL USPESNE DOKONCENY. VSETKY DATA SU V DB! <<"
echo "========================================================"