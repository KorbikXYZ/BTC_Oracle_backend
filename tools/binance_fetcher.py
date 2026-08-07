import os
import json
import sys
import time
import urllib.request
import datetime
import pandas as pd

# configuration and environment loading
import config

# CLI argument parsing and default interval configuration
cli_interval = None
if len(sys.argv) > 1:
    if sys.argv[1] in ["--minute", "--day"]:
        cli_interval = sys.argv[1]

chosen_interval = cli_interval if cli_interval else config.DEFAULT_INTERVAL

# dynamic determination of output parquet filename
output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

if chosen_interval == "--minute":
    binance_interval = "1m"
    time_delta_step = pd.Timedelta(minutes=1)
    filename = config.FILENAME_MINUTE
    print("[DEBUG] Rezim: 1-minutove sviecky (--minute)")
else:
    binance_interval = "1d"
    time_delta_step = pd.Timedelta(days=1)
    filename = config.FILENAME_DAY
    print("[DEBUG] Rezim: Denne sviecky (--day)")

abs_parquet_path = os.path.join(output_dir, filename)


# incremental downloading of binance price candles
def download_binance_prices_sync(out_parquet_path, interval_str, step_delta):
    base_url = config.BINANCE_BASE_URL.rstrip("/")
    if "api" not in base_url:
        base_url = base_url.replace("binance.com", "://binance.com")
    if "/api/v3/klines" not in base_url:
        base_url += "/api/v3/klines"
        
    existing_df = None
    current_start_ts = int(config.DEFAULT_START_DATE.timestamp() * 1000)
    
    if os.path.exists(out_parquet_path):
        try:
            existing_df = pd.read_parquet(out_parquet_path)
            if not existing_df.empty and 'datum' in existing_df.columns:
                print(f"[DEBUG] Nasiel sa existujuci subor: {os.path.basename(out_parquet_path)}")     
                
                # remove unclosed day 
                existing_df['datum'] = pd.to_datetime(existing_df['datum'])
                last_date_frozen = existing_df['datum'].max()
                existing_df = existing_df[existing_df['datum'] < last_date_frozen].copy()
                print(f"[DEBUG] Odstránený posledný neuzavretý deň: {last_date_frozen.strftime('%Y-%m-%d')}")
                
                last_date = pd.to_datetime(existing_df['datum']).max()
                next_step = last_date + step_delta
                current_start_ts = int(next_step.timestamp() * 1000)
                print(f"[DEBUG] Posledny zaznam v databaze: {last_date}")
                print(f"[DEBUG] Budem stahovat data od: {next_step}")
                
        except Exception as e:
            print(f"[DEBUG] Chyba pri citani Parquet suboru (bude vytvoreny nanovo): {e}")

    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    
    if current_start_ts >= now_ts:
        print(f"-> Data v {os.path.basename(out_parquet_path)} su aktualne. Nie je potrebne stahovat.")
        return

    print(f"-> Stahujem chybuce sviecky {config.DEFAULT_SYMBOL} (interval: {interval_str}) z {base_url}...")
    all_klines = []
    
    while current_start_ts < now_ts:
        url = f"{base_url}?symbol={config.DEFAULT_SYMBOL}&interval={interval_str}&startTime={current_start_ts}&limit={config.API_MAX_LIMIT}"
        try:
            req = urllib.request.Request(url, headers=config.HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT_SECONDS) as response:
                klines_chunk = json.loads(response.read().decode("utf-8"))
            
            if not klines_chunk: 
                break
            
            if all_klines and all_klines[-1] == klines_chunk:
                all_klines += klines_chunk[1:]
            else:
                all_klines += klines_chunk
                
            # extraction of timestamp from latest candle in chunk
            last_downloaded_ts = int(klines_chunk[-1][0])
            
            if len(all_klines) % config.PROGRESS_PRINT_INTERVAL_ROWS == 0 or last_downloaded_ts >= now_ts:
                current_date_status = datetime.datetime.fromtimestamp(last_downloaded_ts / 1000.0, tz=datetime.timezone.utc)
                print(f"[PROGRESS] Celkovo nacitanych riadkov: {len(all_klines)}. Aktualny cas na serveri: {current_date_status.date()}")
            
            if last_downloaded_ts <= current_start_ts: 
                break
            
            current_start_ts = last_downloaded_ts + 1
            time.sleep(config.SUCCESS_SLEEP_SECONDS)
            
        except Exception as e: 
            print(f"X Chyba pocas stahovania bloku z Binance: {e}")
            print(f"-> Skusam pockat {config.ERROR_SLEEP_SECONDS} sekund a pokracovat...")
            time.sleep(config.ERROR_SLEEP_SECONDS)
            continue

    if not all_klines:
        print("-> Nezoznamili sa ziadne nove data na stiahnutie.")
        return

    # parsing of raw klines into list of records
    new_data = []
    for kline in all_klines:
        # extraction of date timestamp and close price
        dt_object = datetime.datetime.fromtimestamp(int(kline[0]) / 1000.0, tz=datetime.timezone.utc)
        cena = round(float(kline[4]), 2)
        new_data.append({"datum": dt_object, "cena_btc_usdt": cena})
    
    new_df = pd.DataFrame(new_data)
    new_df['datum'] = pd.to_datetime(new_df['datum']).dt.tz_localize(None)
    
    if existing_df is not None:
        existing_df['datum'] = pd.to_datetime(existing_df['datum'])
        final_df = pd.concat([existing_df, new_df], ignore_index=True)
        final_df = final_df.drop_duplicates(subset=['datum'], keep='last')
    else:
        final_df = new_df
        
    final_df = final_df.sort_values('datum').reset_index(drop=True)
    
    file_dir = os.path.dirname(out_parquet_path)
    if file_dir and not os.path.exists(file_dir):
        os.makedirs(file_dir, exist_ok=True)
        
    final_df.to_parquet(out_parquet_path, index=False, engine='pyarrow')
    print(f"-> Aktualizacia dokoncena. Pridanych {len(new_df)} novych zaznamov.")
    print(f"-> Celkovo je v {os.path.basename(out_parquet_path)} ulozenych {len(final_df)} zaznamov.")

if __name__ == "__main__":
    download_binance_prices_sync(abs_parquet_path, binance_interval, time_delta_step)