import os
import sys
import json
import urllib.request
import datetime
from io import StringIO
import pandas as pd

# addition of tools directory to system path for config import
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(script_dir)

import config

# resolution of absolute path to output parquet file
output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

abs_parquet_path = os.path.join(output_dir, config.FILENAME_ONCHAIN)

# fetching of real on-chain dataset from source
def fetch_real_onchain_data(out_parquet_path):
    url = config.GITHUBUSERCONTENT_URL.rstrip("/")
    if "coinmetrics" not in url:
        url += "/coinmetrics/data/master/csv/btc.csv"
        
    print(f"-> Stahujem kompletny surovy on-chain dataset z {url}...")
    
    try:
        req = urllib.request.Request(url, headers=config.HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=config.ONCHAIN_REQUEST_TIMEOUT_SECONDS) as response:
            html_text = response.read().decode("utf-8")
            
        # loading of raw csv dataset
        df_online = pd.read_csv(StringIO(html_text))
        
        # normalization of timestamp column to date
        df_online['date'] = pd.to_datetime(df_online['time']).dt.normalize()
        df_online = df_online.drop(columns=['time'], errors='ignore')
        
        # removal of timezone and sorting of date records
        df_online['date'] = df_online['date'].dt.tz_localize(None)
        df_online = df_online.sort_values('date').drop_duplicates('date', keep='last').reset_index(drop=True)
        
        # creation of output directory if missing
        file_dir = os.path.dirname(out_parquet_path)
        if file_dir and not os.path.exists(file_dir):
            os.makedirs(file_dir, exist_ok=True)

        # writing of full dataset to parquet file
        df_online.to_parquet(out_parquet_path, index=False, engine='pyarrow')
        
        print(f"-> On-chain data uspesne zosynchronizovane do Parquet suboru.")
        print(f"-> Celkovo je v {os.path.basename(out_parquet_path)} ulozenych {len(df_online)} dni a {len(df_online.columns)} stlpcov.")
        
    except Exception as e: 
        print(f"!!! CHYBA PRI STAHOVANI ON-CHAIN DATABAZY: {e}")


if __name__ == "__main__":
    fetch_real_onchain_data(abs_parquet_path)