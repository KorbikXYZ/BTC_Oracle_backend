import os
import sys
import json
import datetime
import importlib.util
import urllib.request
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.collections import LineCollection

# addition of /tools directory to system path for config import
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
tools_dir = os.path.join(project_root, "tools")
sys.path.insert(0, tools_dir)

import config

# safe direct import of db_exporter via absolute path
db_exporter_path = os.path.join(tools_dir, "db_exporter.py")
if not os.path.exists(db_exporter_path):
    raise FileNotFoundError(f"Kriticka chyba: Subor {db_exporter_path} sa nenasiel!")

spec = importlib.util.spec_from_file_location("db_exporter", db_exporter_path)
db_exporter = importlib.util.module_from_spec(spec)
sys.modules["db_exporter"] = db_exporter
spec.loader.exec_module(db_exporter)

# construction of absolute paths to parquet databases
output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

parquet_onchain_path = os.path.join(output_dir, config.FILENAME_ONCHAIN)
parquet_fng_path = os.path.join(output_dir, config.FILENAME_FNG)
parquet_DUNE_path = os.path.join(output_dir, config.FILENAME_DUNE_BTC)
manual_txt_path = os.path.join(output_dir, config.FILENAME_TXT_MANUAL)

def run_integrated_onchain_analysis(onchain_p_path, fng_p_path):
    print(f"-> [START] Nacitavam on-chain data: {onchain_p_path}")
    print(f"-> [START] Nacitavam sentiment data: {fng_p_path}")
    
    if not os.path.exists(onchain_p_path) or not os.path.exists(fng_p_path):
        raise FileNotFoundError("Chyba: Niektory z Parquet suborov neexistuje.")

    # loading of raw fear and greed sentiment data
    df_fng_raw = pd.read_parquet(fng_p_path)
    df_fng = pd.DataFrame()
    df_fng['date'] = pd.to_datetime(df_fng_raw['date']).dt.normalize()
    df_fng['fng'] = df_fng_raw['fng_value'].astype(float)

    # processing and insertion of clean on-chain history
    print("-> [KROK 1] Spracovavam ciste on-chain data z Parquet suboru...")
    df_raw_onchain = pd.read_parquet(onchain_p_path)
    df_raw_onchain['date'] = pd.to_datetime(df_raw_onchain['date']).dt.normalize()
    
    df_pure = pd.DataFrame()
    df_pure['date'] = df_raw_onchain['date']
    df_pure['market_cap'] = pd.to_numeric(df_raw_onchain['CapMrktCurUSD'], errors='coerce')
    df_pure['mvrv_ratio'] = pd.to_numeric(df_raw_onchain['CapMVRVCur'], errors='coerce')
    df_pure['btc_price'] = pd.to_numeric(df_raw_onchain['PriceUSD'], errors='coerce')
    
    if 'CapRealUSD' in df_raw_onchain.columns:
        df_pure['realized_cap'] = pd.to_numeric(df_raw_onchain['CapRealUSD'], errors='coerce')
    else:
        df_pure['realized_cap'] = df_pure['market_cap'] / df_pure['mvrv_ratio']

    # loading of manual txt overrides for clean history and widgets
    manual_txt_path = os.path.join(output_dir, config.FILENAME_TXT_MANUAL)
    if os.path.exists(manual_txt_path):
        try:
            print(f"-> [MANUAL DATA] Nacitavam manualny subor: {manual_txt_path}")
            df_manual = pd.read_csv(manual_txt_path, sep=r'\s+')
            df_manual['date'] = pd.to_datetime(df_manual['date']).dt.normalize()
            df_manual['circulating_supply'] = pd.to_numeric(df_manual['circulating_supply'], errors='coerce')
            df_manual['realized_price'] = pd.to_numeric(df_manual['realized_price'], errors='coerce')
            
            # merging manual data to fill missing gaps
            df_pure = pd.merge(df_pure, df_manual, on='date', how='left')
            
            # fallback calculation of market and realized caps from manual entries
            m_cap_calc = df_pure['btc_price'] * df_pure['circulating_supply']
            r_cap_calc = df_pure['realized_price'] * df_pure['circulating_supply']
            
            df_pure['market_cap'] = df_pure['market_cap'].fillna(m_cap_calc)
            df_pure['realized_cap'] = df_pure['realized_cap'].fillna(r_cap_calc)
            
            # cleanup of temporary helper columns
            df_pure = df_pure.drop(columns=['circulating_supply', 'realized_price'])
            print("-> [MANUAL DATA] Chybejuce data uspesne doplnene do zakladnej osi.")
        except Exception as manual_err:
            print(f"[MANUAL DATA ERROR] Chyba pri citani manualneho TXT suboru: {manual_err}")
    else:
        print(f"-> [MANUAL DATA ALERT] Manualny subor {manual_txt_path} nebol najdeny. Pokracujem bez neho.")
    
    # cleanup of missing base metrics in on-chain dataset
    df_pure_clean = df_pure.dropna(subset=['btc_price', 'market_cap', 'realized_cap']).copy()

    # calculation of z-scores and rolling metrics for history
    df_pure_clean['Cap_Diff'] = df_pure_clean['market_cap'] - df_pure_clean['realized_cap']
    df_pure_clean['Market_Cap_Std'] = df_pure_clean['market_cap'].expanding(min_periods=config.EXPANDING_MIN_PERIODS).std()
    df_pure_clean['onchain_z'] = (df_pure_clean['Cap_Diff'] / df_pure_clean['Market_Cap_Std']).fillna(0)
    df_pure_clean['realized_proxy'] = df_pure_clean['btc_price'].rolling(window=config.CYKLUS_DNI, min_periods=config.ROLLING_MIN_PERIODS).mean()
    df_pure_clean['okno_std'] = df_pure_clean['btc_price'].rolling(window=config.CYKLUS_DNI, min_periods=config.ROLLING_MIN_PERIODS).std()
    df_pure_clean['mvrv_z'] = ((df_pure_clean['btc_price'] - df_pure_clean['realized_proxy']) / df_pure_clean['okno_std']).fillna(0)
    df_pure_clean['price'] = df_pure_clean['btc_price']

    # merging clean metrics with fear and greed history
    df_history = pd.merge(df_pure_clean, df_fng, on='date', how='inner').sort_values('date').reset_index(drop=True)

    # database connection initialization
    conn = db_exporter.get_db_connection()
    try:
        db_exporter.init_database(conn)

        # retrieval of last recorded date for fear and greed
        posledny_fng_datum = db_exporter.get_last_recorded_date(conn, "fear_and_greed")

        if posledny_fng_datum is None:
            print("-> [DB FNG BACKFILL] V DB nie su ziadne FNG data. Spustam kompletny backfill...")
            df_fng_missing = df_fng.copy()
        else:
            posledny_fng_ts = pd.Timestamp(posledny_fng_datum)
            df_fng_missing = df_fng[df_fng['date'] > posledny_fng_ts].copy()
            
            print(f"-> [DB FNG CHECK] Posledny zapis FNG v DB je z: {posledny_fng_datum.strftime('%Y-%m-%d')}.")
            print(f"-> [DB FNG CHECK] Doplnam do btc_metrics_series: {len(df_fng_missing)} FNG dni.")

        # insertion of missing fear and greed entries
        fng_counter = 0
        for idx, row in df_fng_missing.iterrows():
            fng_date_str = row['date'].strftime('%Y-%m-%d')
            db_exporter.save_metric_value(conn, fng_date_str, "fear_and_greed", row['fng'])
            fng_counter += 1

        if fng_counter > 0:
            print(f"-> [POSTGRES] Uspesne zapisanych {fng_counter} FNG dni do {config.DB_TABLE_TIME_SERIES}.")

        # incremental backfill of verified on-chain metrics
        posledny_db_datum = db_exporter.get_last_recorded_date(conn, f"mvrv_rolling_z_{config.CYKLUS_DNI}")
        
        if posledny_db_datum is None:
            print("-> [DB BACKFILL] V DB nie su ziadne data. Spustam kompletny backfill overenych dat...")
            df_missing = df_history.copy()
        else:
            posledny_db_ts = pd.Timestamp(posledny_db_datum)
            df_missing = df_history[df_history['date'] > posledny_db_ts].copy()
            
            print(f"-> [DB CHECK] Posledny zapis v DB je z: {posledny_db_datum.strftime('%Y-%m-%d')}.")
            print(f"-> [DB CHECK] Doplnam do btc_metrics_series: {len(df_missing)} overenych dni.")

        backfill_counter = 0
        for idx, row in df_missing.iterrows():
            m_date_str = row['date'].strftime('%Y-%m-%d')
            db_exporter.save_metric_value(conn, m_date_str, "btc_price", row['price'])
            db_exporter.save_metric_value(conn, m_date_str, "mvrv_rolling_z_"+str(config.CYKLUS_DNI), row['mvrv_z'])
            db_exporter.save_metric_value(conn, m_date_str, "mvrv_global_z", row['onchain_z'])
            backfill_counter += 1

        if backfill_counter > 0:
            print(f"-> [POSTGRES] Uspesne zapisanych {backfill_counter} realnych dni do {config.DB_TABLE_TIME_SERIES}.")


        # addition of latest market data for charts and UI widgets
        print("\n" + "="*60)
        print("-> [DEBUG KROK 2] SPUŠŤAM ANALÝZU PRE FLUTTER WIDGETY")
        print("="*60)
        
        binance_parquet_path = os.path.abspath(os.path.join(os.path.dirname(onchain_p_path), "BTC_1d.parquet"))
        if not os.path.exists(binance_parquet_path):
            raise FileNotFoundError(f"Kriticka chyba: Binance subor {binance_parquet_path} neexistuje!")
            
        df_binance = pd.read_parquet(binance_parquet_path)
        df_base = pd.DataFrame()
        df_base['date'] = pd.to_datetime(df_binance['datum']).dt.normalize()
        df_base['btc_price'] = pd.to_numeric(df_binance['cena_btc_usdt'], errors='coerce')
        
        df_base = df_base.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
        print(f"[DEBUG 2.1] Nacitany Binance kalendar: {len(df_base)} dni. Rozsah: {df_base['date'].min().date()} az {df_base['date'].max().date()}")
        
        # combination of base dates with extended on-chain data
        df_pure_tmp = df_pure.drop(columns=['btc_price'], errors='ignore').drop_duplicates(subset=['date'])
        df_extended = pd.merge(df_base, df_pure_tmp, on='date', how='left').sort_values('date').reset_index(drop=True)
        print(f"[DEBUG 2.2] Po zluceni s On-Chain Parquetom: {len(df_extended)} dni.")

        # selection between dune network data and mathematical extrapolation
        if getattr(config, 'USE_DUNE_DATA', True) and os.path.exists(parquet_DUNE_path):
            try:
                print("-> [DUNE MODE] Nacitavam realne on-chain data z Dune...")
                df_dune = pd.read_parquet(parquet_DUNE_path)
                df_dune['date'] = pd.to_datetime(df_dune['date']).dt.normalize().dt.tz_localize(None)
                
                df_dune['current_price'] = pd.to_numeric(df_dune['current_price'], errors='coerce')
                df_dune['realized_price'] = pd.to_numeric(df_dune['realized_price'], errors='coerce')
                df_dune['circulating_supply'] = pd.to_numeric(df_dune['circulating_supply'], errors='coerce')
                
                df_dune['dune_market_cap'] = df_dune['current_price'] * df_dune['circulating_supply']
                df_dune['dune_realized_cap'] = df_dune['realized_price'] * df_dune['circulating_supply']
                
                df_dune_clean = df_dune[['date', 'dune_market_cap', 'dune_realized_cap']].drop_duplicates(subset=['date'])
                df_extended = pd.merge(df_extended, df_dune_clean, on='date', how='left')
                
                df_extended['market_cap'] = df_extended['market_cap'].fillna(df_extended['dune_market_cap'])
                df_extended['realized_cap'] = df_extended['realized_cap'].fillna(df_extended['dune_realized_cap'])
                df_extended = df_extended.drop(columns=['dune_market_cap', 'dune_realized_cap'])
                print(f"[DEBUG DUNE] Uspesne doplnene realne data z Dune.")
            except Exception as dune_err:
                print(f"[DEBUG DUNE ERROR] Chyba pri spracovani Dune dat: {dune_err}")
        else:
            # fallback extrapolation mode for missing on-chain entries
            print("-> [EXTRAPOLATION MODE] Spustam matematicke dopocitavanie kapitalizacii (Emisia + Realized Proxy)...")
            df_extended = df_extended.sort_values('date').reset_index(drop=True)
            
            # supply estimation using daily post-halving emission rate
            supply_series = df_extended['market_cap'] / df_extended['btc_price']
            last_valid_idx = supply_series.last_valid_index()
            
            if last_valid_idx is not None:
                last_valid_supply = supply_series.loc[last_valid_idx]
                last_valid_date = df_extended.loc[last_valid_idx, 'date']
                
                for idx in range(last_valid_idx + 1, len(df_extended)):
                    dni_rozdiel = (df_extended.loc[idx, 'date'] - last_valid_date).days
                    extrapolated_supply = last_valid_supply + (dni_rozdiel * 164.25)
                    
                    # realized price projection via rolling historical values
                    realized_price_series = df_extended['realized_cap'] / supply_series
                    last_realized_price = realized_price_series.loc[:last_valid_idx].ffill().iloc[-1]
                    
                    # market and realized cap calculation for current step
                    df_extended.loc[idx, 'market_cap'] = df_extended.loc[idx, 'btc_price'] * extrapolated_supply
                    df_extended.loc[idx, 'realized_cap'] = last_realized_price * extrapolated_supply

        # removal of invalid price entries and forward fill of cap values
        df_clean = df_extended.dropna(subset=['btc_price']).copy()
        df_clean['market_cap'] = df_clean['market_cap'].ffill()
        df_clean['realized_cap'] = df_clean['realized_cap'].ffill()

        print(f"[DEBUG 2.5] Po dropna (vyhodenie NaN riadkov): Ostalo {len(df_clean)} dni.")

        # full recalculation of oscillators without series truncation
        df_clean['Cap_Diff'] = df_clean['market_cap'] - df_clean['realized_cap']
        df_clean['Market_Cap_Std'] = df_clean['market_cap'].expanding(min_periods=config.EXPANDING_MIN_PERIODS).std()
        df_clean['onchain_z'] = (df_clean['Cap_Diff'] / df_clean['Market_Cap_Std']).ffill().bfill().fillna(0)
        
        df_clean['realized_proxy'] = df_clean['btc_price'].rolling(window=config.CYKLUS_DNI, min_periods=config.ROLLING_MIN_PERIODS).mean()
        df_clean['okno_std'] = df_clean['btc_price'].rolling(window=config.CYKLUS_DNI, min_periods=config.ROLLING_MIN_PERIODS).std()
        df_clean['mvrv_z'] = ((df_clean['btc_price'] - df_clean['realized_proxy']) / df_clean['okno_std']).fillna(0)
        df_clean['price'] = df_clean['btc_price']
        
        # left join with sentiment dataset
        df_fng_clean = df_fng.drop_duplicates(subset=['date'])
        df = pd.merge(df_clean, df_fng_clean, on='date', how='left')
        df['fng'] = df['fng'].ffill().fillna(50)
        df = df.sort_values('date').reset_index(drop=True)
        
        # filtering out future dates and unverified current day
        dnesny_datum = pd.Timestamp.now().normalize()
        df = df[df['date'] < dnesny_datum].copy()


        print(f"[DEBUG 2.7] Konecny stav po optimalizovanom zluceni: {len(df)} riadkov.")
        print(f"            Konecny maximalny datum v celom skripte: {df['date'].max().date()}")
        print("="*60 + "\n")

        # extraction of latest metrics for report generation
        aktualna_cena = df['price'].iloc[-1]
        aktualne_z_score = df['mvrv_z'].iloc[-1]
        aktualne_onchain_z = df['onchain_z'].iloc[-1]
        aktualny_fng = df['fng'].iloc[-1]
        aktualny_datum = df['date'].iloc[-1].strftime('%Y-%m-%d')
        # calculation of full historical timeline starting from 2009
        print("-> [FULL CALC] Spustam nezavisly vypocet full historie od roku 2009...")
        
        # initialization with clean base containing manual data
        df_full_calc = df_pure.dropna(subset=['btc_price']).copy()
        
        # synchronization with recent binance timeline up to current date
        max_pure_date = df_full_calc['date'].max()
        df_new_days = df_extended[df_extended['date'] > max_pure_date][['date', 'btc_price', 'market_cap', 'realized_cap']].copy()
        
        if not df_new_days.empty:
            df_full_calc = pd.concat([df_full_calc, df_new_days], ignore_index=True).sort_values('date').reset_index(drop=True)
            
        # cap extrapolation for full timeline when dune mode is inactive
        if not getattr(config, 'USE_DUNE_DATA', True) or not os.path.exists(parquet_DUNE_path):
            supply_series_f = df_full_calc['market_cap'] / df_full_calc['btc_price']
            last_v_idx = supply_series_f.last_valid_index()
            if last_v_idx is not None:
                last_valid_supply_f = supply_series_f.loc[last_v_idx]
                last_valid_date_f = df_full_calc.loc[last_v_idx, 'date']
                
                for idx in range(last_v_idx + 1, len(df_full_calc)):
                    dni_rozdiel_f = (df_full_calc.loc[idx, 'date'] - last_valid_date_f).days
                    extrapolated_supply_f = last_valid_supply_f + (dni_rozdiel_f * 164.25)
                    
                    realized_price_series_f = df_full_calc['realized_cap'] / supply_series_f
                    last_realized_price_f = realized_price_series_f.loc[:last_v_idx].ffill().iloc[-1]
                    
                    df_full_calc.loc[idx, 'market_cap'] = df_full_calc.loc[idx, 'btc_price'] * extrapolated_supply_f
                    df_full_calc.loc[idx, 'realized_cap'] = last_realized_price_f * extrapolated_supply_f

        # mathematical recalculation for isolated full dataframe
        df_full_calc['market_cap'] = df_full_calc['market_cap'].ffill()
        df_full_calc['realized_cap'] = df_full_calc['realized_cap'].ffill()
        df_full_calc['Cap_Diff'] = df_full_calc['market_cap'] - df_full_calc['realized_cap']
        df_full_calc['Market_Cap_Std'] = df_full_calc['market_cap'].expanding(min_periods=config.EXPANDING_MIN_PERIODS).std()
        df_full_calc['onchain_z'] = (df_full_calc['Cap_Diff'] / df_full_calc['Market_Cap_Std']).ffill().bfill().fillna(0)
        
        # trimming future dates consistent with primary timeline
        df_full_calc = df_full_calc[df_full_calc['date'] < dnesny_datum].copy()
        print(f"-> [FULL CALC DONE] Full os pripravena. Rozsah: {df_full_calc['date'].min().date()} az {df_full_calc['date'].max().date()} ({len(df_full_calc)} riadkov).")
        
        # chart generation and database export preparation
        if aktualne_onchain_z > config.MVRV_Z_SCORE_LIMIT_HIGH:
            onchain_stav = config.STATUS_ONCHAIN_OVERBOUGHT
            label_color = config.COLOR_STRONG_OVERVALUED
        elif config.MVRV_Z_SCORE_LIMIT_MID < aktualne_onchain_z <= config.MVRV_Z_SCORE_LIMIT_HIGH:
            onchain_stav = config.STATUS_ONCHAIN_MID_HIGH
            label_color = config.COLOR_OVERVALUED
        elif config.MVRV_Z_SCORE_LIMIT_LOW <= aktualne_onchain_z <= config.MVRV_Z_SCORE_LIMIT_MID:
            onchain_stav = config.STATUS_ONCHAIN_NEUTRAL
            label_color = config.COLOR_NEUTRAL
        else:
            onchain_stav = config.STATUS_ONCHAIN_OVERSOLD
            label_color = config.COLOR_STRONG_UNDERVALUED

        # formatting output for console and text summary
        vystup_text = [
            "="*60,
            f" COINMETRICS LIVE ON-CHAIN REPORT | ({aktualny_datum})",
            "="*60,
            f"Aktualna trhova cena     : ${aktualna_cena:,.2f}",
            f"Plavajuce Z-Score ({config.CYKLUS_DNI}d) : {aktualne_z_score:+.3f}",
            f"Tvoje On-Chain MVRV Z    : {aktualne_onchain_z:+.3f}",
            f"Fear & Greed Sentiment   : {aktualny_fng:.0f}/100",
            f"STATISTICKY ON-CHAIN STAV: {onchain_stav}",
            "="*60
        ]
        print("\n" + "\n".join(vystup_text) + "\n")

        summary_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_SUMMARY_DIR))
        os.makedirs(summary_dir, exist_ok=True)
        txt_path = os.path.join(summary_dir, f"{config.POWER_LAW_ONCHAIN_FILENAME}_{config.CYKLUS_DNI}d.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vystup_text))

        # rendering backend matplotlib visualization
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=config.GRAPH_SIZE_ONCHAIN_REPORT, sharex=True, facecolor='black')
        for ax in [ax1, ax2, ax3]:
            ax.set_facecolor('black')
            ax.tick_params(colors='white', labelsize=10)
            ax.grid(True, color='#1c1c1c', linestyle='-', linewidth=0.5)

        # price and sentiment heatmap panel
        ax1.set_yscale('log')
        ax1.set_title('Bitcoin Live Price & Fear and Greed Heatmap', color='white', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Price (USD)', color='white', fontsize=10)
        df['date_float'] = mdates.date2num(df['date'])
        points = np.array([df['date_float'].values, df['price'].values]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        norm_fng = plt.Normalize(0, 100)
        lc = LineCollection(segments, cmap='RdYlGn', norm=norm_fng, linewidths=2.2)
        lc.set_array(df['fng'].values)
        ax1.add_collection(lc)
        ax1.xaxis_date()
        ax1.set_ylim(df['price'].min() * 0.9, df['price'].max() * 1.1)
        cbar_ax = fig.add_axes([0.93, 0.66, 0.015, 0.22])
        cbar = fig.colorbar(lc, cax=cbar_ax)
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
        ax1.text(0.95, 0.40, f"SENTIMENT: {aktualny_fng:.0f}/100", color='white', fontsize=10, fontweight='bold', bbox=dict(facecolor='#222222', alpha=0.8, edgecolor='white', boxstyle='round,pad=0.5'), transform=ax1.transAxes, ha='right', va='top')

        # rolling z-score oscillator panel
        ax2.set_title(f'Plavajuce Z-Score Oscillator (Okno: {config.CYKLUS_DNI} dni)', color='white', fontsize=11)
        ax2.set_ylabel('Z-Score', color='white', fontsize=10)
        max_y_limit_mvrv = max(df['mvrv_z'].max() * 1.15, 3.0)
        min_y_limit_mvrv = df['mvrv_z'].min() - 0.5
        ax2.set_ylim(min_y_limit_mvrv, max_y_limit_mvrv)
        ax2.plot(df['date'], df['mvrv_z'], color='#e1b12c', linewidth=1.2, label='Plavajuce Z-Score')
        ax2.fill_between(df['date'], df['mvrv_z'], 0, where=(df['mvrv_z'] >= 0), color='green', alpha=0.3, interpolate=True)
        ax2.fill_between(df['date'], df['mvrv_z'], 0, where=(df['mvrv_z'] < 0), color='brown', alpha=0.3, interpolate=True)
        ax2.axhspan(2.0, max_y_limit_mvrv, color='#c0392b', alpha=0.15, label='Overbought Zone')
        ax2.axhspan(min_y_limit_mvrv, -0.5, color='#16a085', alpha=0.15, label='Oversold Zone')
        ax2.axhline(y=0, color='grey', linestyle=':', linewidth=1)
        ax2.text(0.95, 0.90, f"PLAVAJUCE Z-SCORE: {aktualne_z_score:+.3f}", transform=ax2.transAxes, ha='right', va='top', color='white', fontsize=9, fontweight='bold', bbox=dict(facecolor='#222222', alpha=0.8, edgecolor='#e1b12c', boxstyle='round,pad=0.4'))
        ax2.legend(facecolor='#111111', edgecolor='#333333', labelcolor='white', loc='upper left', fontsize=9)

        # global mvrv z-score panel
        ax3.set_title('Tvoj On-Chain MVRV Z-Score (Vypocet podla Cap_Diff / Market_Cap_Std)', color='white', fontsize=11)
        ax3.set_ylabel('MVRV Z-Score', color='white', fontsize=10)
        max_y_limit_onchain = df['onchain_z'].max() * 1.15
        min_y_limit_onchain = df['onchain_z'].min() - 0.5
        ax3.set_ylim(min_y_limit_onchain, max_y_limit_onchain)
        ax3.plot(df['date'], df['onchain_z'], color='#3498db', linewidth=1.5, label='On-Chain MVRV Z')
        ax3.fill_between(df['date'], df['onchain_z'], 0, where=(df['onchain_z'] >= 0), color='green', alpha=0.3, interpolate=True)
        ax3.fill_between(df['date'], df['onchain_z'], 0, where=(df['onchain_z'] < 0), color='brown', alpha=0.3, interpolate=True)
        ax3.axhspan(2.0, max_y_limit_onchain, color='#c0392b', alpha=0.15, label='Overbought Zone')
        ax3.axhspan(min_y_limit_onchain, -0.2, color='#16a085', alpha=0.15, label='Oversold Zone')
        ax3.axhline(y=0, color='#ffffff', linestyle='-', linewidth=0.8, alpha=0.5)
        ax3.text(0.95, 0.90, f"AKTUALNE ON-CHAIN MVRV Z: {aktualne_onchain_z:+.3f}", transform=ax3.transAxes, ha='right', va='top', color='white', fontsize=9, fontweight='bold', bbox=dict(facecolor=label_color, alpha=0.85, edgecolor='black', boxstyle='round,pad=0.4'))
        ax3.legend(facecolor='#111111', edgecolor='#333333', labelcolor='white', loc='upper left', fontsize=9)

        ax3.set_xlim(df['date'].min(), df['date'].max())
        plt.subplots_adjust(left=0.08, right=0.89, top=0.94, bottom=0.05, hspace=0.3)

        graphs_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_GRAPHS_DIR))
        os.makedirs(graphs_dir, exist_ok=True)
        graph_path = os.path.join(graphs_dir, f"{config.POWER_LAW_ONCHAIN_FILENAME}_{config.CYKLUS_DNI}d.png")
        plt.savefig(graph_path, dpi=300, facecolor='black')
        plt.close()
        print(f"-> On-chain graf bol uspesne ulozeny do '{graph_path}'.")

        # export of chart snapshots to postgresql database
        if config.FLUTTER_CHART_SNAPSHOT_DAYS is None:
            df_chart = df.copy()
        else:
            df_chart = df.tail(config.FLUTTER_CHART_SNAPSHOT_DAYS).copy()
            
        timestamps = [int(dt.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.timezone.utc).timestamp()) for dt in df_chart['date']]


        # remapping full scale onchain values to subset timeframe
        df_full_mapping = df_full_calc[['date', 'onchain_z']].drop_duplicates(subset=['date'])
        df_chart = df_chart.drop(columns=['onchain_z'], errors='ignore')
        df_chart = pd.merge(df_chart, df_full_mapping, on='date', how='left').fillna({'onchain_z': 0})
            

        # setup of structured report output payload
        table_output_data = {
            "report_date": aktualny_datum,
            "rows": [
                {
                    "key": "btc_price", 
                    "label": "Aktualna trhova cena", 
                    "raw_value": float(aktualna_cena), 
                    "display_value": f"${aktualna_cena:,.2f}"
                },
                {
                    "key": f"mvrv_rolling_z_{config.CYKLUS_DNI}d", 
                    "label": f"Plavajuce Z-Score ({config.CYKLUS_DNI}d)", 
                    "raw_value": float(aktualne_z_score), 
                    "display_value": f"{aktualne_z_score:+.3f}"
                },
                {
                    "key": "mvrv_global_z", 
                    "label": "Tvoje On-Chain MVRV Z", 
                    "raw_value": float(aktualne_onchain_z), 
                    "display_value": f"{aktualne_onchain_z:+.3f}"
                },
                {
                    "key": "fear_and_greed", 
                    "label": "Fear & Greed Sentiment", 
                    "raw_value": float(aktualny_fng), 
                    "display_value": f"{aktualny_fng:.0f}/100"
                },
                {
                    "key": "onchain_status", 
                    "label": "STATISTICKY ON-CHAIN STAV", 
                    "raw_value": onchain_stav, 
                    "display_value": onchain_stav
                }
            ],
            "visual_meta": {
                "label_color_hex": label_color  # color key pass to ui elements
            }
        }

        # widget export for price heatmap overview
        spojeny_vystup = "\n".join(vystup_text)
        if config.CYKLUS_DNI == 1460:
            db_exporter.save_chart_document(conn, config.ID_WIDGET_PRICE_HEATMAP, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
                "meta": {"title": config.WIDGET_PRICE_HEATMAP_TITLE, "subtitle": config.WIDGET_PRICE_HEATMAP_SUBTITLE, "primary_metric_name": "BTC Price", "sentiment_score": int(aktualny_fng), "status_tags": ["price", "heatmap", "live"]},
                "chart_config": {"type": "SINGLE_AXIS", "x_axis_type": "datetime", "y_axis_config": {"left": {"label": "Price (USD)", "min": float(df_chart['price'].min() * 0.95), "max": float(df_chart['price'].max() * 1.05)}, "right": None}},
                "chart_data": {"timestamps": timestamps, "datasets": [{"label": "BTC Price", "axis": "left", "color": config.COLOR_FLUTTER_BTC, "values": df_chart['price'].round(2).tolist()}, {"label": "Fear & Greed Mask", "axis": "left", "color": config.COLOR_FLUTTER_FNG_MASK, "values": df_chart['fng'].astype(int).tolist()}]},
                "ai_content": {"summary": f"Aktualna cena BTC je ${aktualna_cena:,.2f} so sentimentom {aktualny_fng:.0f}/100.\n{spojeny_vystup}", "model_version": config.MODEL_VERSION_FNG_HEATMAP},
                "table_output": table_output_data
            }, has_access=True, is_premium=False)

        # widget export for cyclic rolling z-score
        widget_id_subor = f"{config.ID_WIDGET_ROLLING_Z}_{config.CYKLUS_DNI}d"
        
        db_exporter.save_chart_document(conn, widget_id_subor, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
            "meta": {"title": f"{config.WIDGET_ROLLING_Z_TITLE} ({config.CYKLUS_DNI}d)", "subtitle": config.WIDGET_ROLLING_Z_SUBTITLE, "primary_metric_name": "Rolling Z-Score", "sentiment_score": int(aktualny_fng), "status_tags": [f"rolling_{config.CYKLUS_DNI}d", "oscillator"]},
            "chart_config": {"type": "OSCILLATOR", "x_axis_type": "datetime", "y_axis_config": {"left": {"label": "Z-Score", "min": float(df_chart['mvrv_z'].min() - 0.5), "max": float(df_chart['mvrv_z'].max() * 1.1)}, "right": None}},
            "chart_data": {"timestamps": timestamps, "datasets": [{"label": f"Z-Score ({config.CYKLUS_DNI}d)", "axis": "left", "color": config.COLOR_FLUTTER_ROLLING_Z, "values": df_chart['mvrv_z'].round(3).tolist()}]},
            "ai_content": {"summary": f"Plavajuce Z-Score pre {config.CYKLUS_DNI}-dnovy cyklus je {aktualne_z_score:+.3f}.", "model_version": config.MODEL_VERSION_ROLLING_Z}
        }, has_access=True, is_premium=False)

        # widget export for global macro mvrv indicators
        if config.CYKLUS_DNI == 1460:
            db_exporter.save_chart_document(conn, config.ID_WIDGET_GLOBAL_MVRV, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
                "meta": {"title": config.WIDGET_GLOBAL_MVRV_TITLE, "subtitle": config.WIDGET_GLOBAL_MVRV_SUBTITLE, "primary_metric_name": "On-Chain MVRV Z", "sentiment_score": int(aktualny_fng), "status_tags": ["macro_onchain", "live"]},
                "chart_config": {"type": "OSCILLATOR", "x_axis_type": "datetime", "y_axis_config": {"left": {"label": "MVRV Z-Score", "min": float(df_chart['onchain_z'].min() - 0.2), "max": float(df_chart['onchain_z'].max() * 1.1)}, "right": None}},
                "chart_data": {"timestamps": timestamps, "datasets": [{"label": "On-Chain MVRV Z-Score", "axis": "left", "color": config.COLOR_FLUTTER_GLOBAL_MVRV, "values": df_chart['onchain_z'].round(3).tolist()}]},
                "ai_content": {"summary": f"Globalny makro stav trhu podla Glassnode metodiky: {onchain_stav}.", "model_version": config.MODEL_VERSION_GLOBAL_MVRV},
                "table_output": table_output_data
            }, has_access=True, is_premium=False)

            # export of complete macro history starting from 2010
            timestamps_full = [int(dt.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.timezone.utc).timestamp()) for dt in df_full_calc['date']]
            df_full_values = df_full_calc['onchain_z'].round(3).tolist()
            
            db_exporter.save_chart_document(conn, f"{config.ID_WIDGET_GLOBAL_MVRV}_full", aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
                "meta": {"title": config.WIDGET_GLOBAL_MVRV_TITLE_FULL, "subtitle": config.WIDGET_GLOBAL_MVRV_SUBTITLE_FULL, "primary_metric_name": "On-Chain MVRV Z Full", "sentiment_score": int(aktualny_fng), "status_tags": ["macro_onchain", "full_history"]},
                "chart_config": {"type": "OSCILLATOR", "x_axis_type": "datetime", "y_axis_config": {"left": {"label": "MVRV Z-Score", "min": float(df_full_calc['onchain_z'].min() - 0.2), "max": float(df_full_calc['onchain_z'].max() * 1.1)}, "right": None}},
                "chart_data": {"timestamps": timestamps_full, "datasets": [{"label": "On-Chain MVRV Z-Score (Full)", "axis": "left", "color": config.COLOR_FLUTTER_GLOBAL_MVRV, "values": df_full_values}]},
                "ai_content": {"summary": f"Kompletna historia makro stavu BTC trhu od roku 2010 do {aktualny_datum}.", "model_version": config.MODEL_VERSION_GLOBAL_MVRV}
            }, has_access=True, is_premium=False)

        print(f"-> [POSTGRES] Vsetky Flutter widgety (vratane FULL verzie) uspesne zapisane.")

    except Exception as e:
        print(f"[EXPORT CRITICAL ERROR] Zlyhal kompletny zluceny export do DB: {e}")
    finally:
        conn.close()
        print("-> [POSTGRES] Spojenie s databazou bolo bezpecne uzatvorene.")


if __name__ == "__main__":
    # parsing command line cycle argument
    if len(sys.argv) > 1:
        try:
            custom_cyklus = int(sys.argv[1])
            config.CYKLUS_DNI = custom_cyklus
            print(f"-> [CLI ARGUMENT] Prepisujem CYKLUS_DNI na: {config.CYKLUS_DNI} dni.")
        except ValueError:
            print(f"-> [CLI WARNING] Argument nie je cislo. Pouzivam default z .env: {config.CYKLUS_DNI}")
    else:
        print(f"-> [DEFAULT] Pouzivam predvoleny cyklus z .env: {config.CYKLUS_DNI}")

    run_integrated_onchain_analysis(parquet_onchain_path, parquet_fng_path)