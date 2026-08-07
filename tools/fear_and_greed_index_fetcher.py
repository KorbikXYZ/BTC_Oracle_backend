import os
import sys
import json
import urllib.request
import datetime
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

abs_parquet_path = os.path.join(output_dir, config.FILENAME_FNG)

# downloading of sentiment data from endpoint
def download_fng_data_sync(out_parquet_path):
    print(f"-> Stahujem zivy sentiment z URL: {config.ALTTERNATIVE_URL}")
    
    existing_df = None
    if os.path.exists(out_parquet_path):
        try:
            existing_df = pd.read_parquet(out_parquet_path)
            if not existing_df.empty and 'date' in existing_df.columns:
                existing_df['date'] = pd.to_datetime(existing_df['date'])
                last_date = existing_df['date'].max()
                print(f"[DEBUG] Nasiel sa existujuci fng subor. Posledny den v DB: {last_date.date()}")
        except Exception as e:
            print(f"[DEBUG] Chyba pri citani existujuceho Parquet suboru (bude vytvoreny nanovo): {e}")

    try:
        req = urllib.request.Request(config.ALTTERNATIVE_URL, headers=config.HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=config.FNG_REQUEST_TIMEOUT_SECONDS) as response:
            raw_res = response.read().decode("utf-8")
        
        fng_json = json.loads(raw_res)
        
        # parsing of json response payload into dict array
        fng_list = []
        for item in fng_json["data"]:
            dt = datetime.datetime.fromtimestamp(int(item["timestamp"])).date()
            fng_list.append({
                "date": dt,
                "fng_value": int(item["value"])
            })
            
        df_online = pd.DataFrame(fng_list)
        df_online['date'] = pd.to_datetime(df_online['date'])
        
        # incremental merging with existing historical data
        if existing_df is not None:
            final_df = pd.concat([existing_df, df_online], ignore_index=True)
            final_df = final_df.drop_duplicates(subset=['date'], keep='last')
        else:
            final_df = df_online

        final_df = final_df.sort_values('date').reset_index(drop=True)

        # creation of output directory if missing
        file_dir = os.path.dirname(out_parquet_path)
        if file_dir and not os.path.exists(file_dir):
            os.makedirs(file_dir, exist_ok=True)

        # writing of final dataframe to parquet file
        final_df.to_parquet(out_parquet_path, index=False, engine='pyarrow')
        
        print(f"-> Sentiment uspesne zosynchronizovany do Parquet suboru.")
        print(f"-> Celkovo je v {os.path.basename(out_parquet_path)} ulozenych {len(final_df)} dni.")
        
    except Exception as e: 
        print(f"X Sietova chyba pri komunikacii s API Alternative: {e}")

if __name__ == "__main__":
    download_fng_data_sync(abs_parquet_path)