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

# addition of tools folder to system path for config import
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
tools_dir = os.path.join(project_root, "tools")
sys.path.insert(0, tools_dir)

import config

# import of db_exporter module using absolute path
db_exporter_path = os.path.join(tools_dir, "db_exporter.py")
if not os.path.exists(db_exporter_path):
    raise FileNotFoundError(f"Kriticka chyba: Subor {db_exporter_path} sa nenasiel!")

spec = importlib.util.spec_from_file_location("db_exporter", db_exporter_path)
db_exporter = importlib.util.module_from_spec(spec)
sys.modules["db_exporter"] = db_exporter
spec.loader.exec_module(db_exporter)

# resolution of absolute paths for input parquet files
output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

parquet_onchain_path = os.path.join(output_dir, config.FILENAME_ONCHAIN)
parquet_fng_path = os.path.join(output_dir, config.FILENAME_FNG)
parquet_DUNE_path = os.path.join(output_dir, config.FILENAME_DUNE_BTC)

DAILY_1D_PARQUET_PATH = os.path.join(output_dir, config.FILENAME_DAY)
manual_txt_path = os.path.join(output_dir, config.FILENAME_TXT_MANUAL)

def run_integrated_onchain_analysis(onchain_p_path, fng_p_path, daily_p_path, manual_t_path, relative_mode=True):
    print(f"-> [START] Nacitavam on-chain data: {onchain_p_path}")
    print(f"-> [START] Nacitavam sentiment data: {fng_p_path}")
    print(f"-> [START] Nacitavam aktualne ceny: {daily_p_path}")
    print(f"-> [START] Nacitavam manualne on-chain data: {manual_t_path}")
    
    if not all(os.path.exists(p) for p in [onchain_p_path, fng_p_path, daily_p_path, manual_t_path]):
        raise FileNotFoundError("Chyba: Niektory zo vstupnych Parquet alebo TXT suborov neexistuje.")

    # loading of fear and greed sentiment data
    df_fng_raw = pd.read_parquet(fng_p_path)
    df_fng = pd.DataFrame()
    df_fng['date'] = pd.to_datetime(df_fng_raw['date']).dt.normalize()
    df_fng['fng'] = df_fng_raw['fng_value'].astype(float)

    # loading of historical on-chain dataset
    df_raw_onchain = pd.read_parquet(onchain_p_path)
    df_raw_onchain['date'] = pd.to_datetime(df_raw_onchain['date']).dt.normalize()
    
    df_pure = pd.DataFrame()
    df_pure['date'] = df_raw_onchain['date']
    df_pure['market_cap'] = pd.to_numeric(df_raw_onchain['CapMrktCurUSD'], errors='coerce')
    df_pure['mvrv_ratio'] = pd.to_numeric(df_raw_onchain['CapMVRVCur'], errors='coerce')
    df_pure['btc_price'] = pd.to_numeric(df_raw_onchain['PriceUSD'], errors='coerce')
    
    # calculation of historical realized cap
    df_pure['realized_cap'] = df_pure['market_cap'] / df_pure['mvrv_ratio']

    # loading of daily price data
    df_1d_raw = pd.read_parquet(daily_p_path)
    df_1d = pd.DataFrame()
    df_1d['date'] = pd.to_datetime(df_1d_raw['datum']).dt.normalize()
    df_1d['btc_price_latest'] = pd.to_numeric(df_1d_raw['cena_btc_usdt'], errors='coerce')

    # loading of manual on-chain data file
    df_manual_raw = pd.read_csv(manual_t_path, sep=r'\s+') 
    df_manual = pd.DataFrame()
    df_manual['date'] = pd.to_datetime(df_manual_raw['date']).dt.normalize()
    df_manual['circulating_supply'] = pd.to_numeric(df_manual_raw['circulating_supply'], errors='coerce')
    df_manual['realized_price'] = pd.to_numeric(df_manual_raw['realized_price'], errors='coerce')
    
    # calculation of updated realized cap
    df_manual['realized_cap_latest'] = df_manual['circulating_supply'] * df_manual['realized_price']

    # merging of all data sources into a unified dataframe
    print("-> [KROK 4] Slucujem historicke data s aktualizovanymi subormi...")
    
    # calculation of historical realized price
    df_pure['realized_price_historical'] = df_pure['btc_price'] / df_pure['mvrv_ratio']

    # outer join with daily price series
    df_pure = pd.merge(df_pure, df_1d, on='date', how='outer')
    
    # outer join with manual on-chain series
    df_pure = pd.merge(df_pure, df_manual, on='date', how='outer')
    
    # chronological sorting of complete dataset
    df_pure = df_pure.sort_values('date').reset_index(drop=True)

    # filling of missing values across sources
    df_pure['btc_price'] = df_pure['btc_price'].fillna(df_pure['btc_price_latest'])
    df_pure['realized_cap'] = df_pure['realized_cap'].fillna(df_pure['realized_cap_latest'])
    df_pure['realized_price'] = df_pure['realized_price'].fillna(df_pure['realized_price_historical'])

    # forward extrapolation for missing daily records
    # generation of supply series from market cap and price
    supply_series = df_pure['market_cap'] / df_pure['btc_price']
    
    last_valid_idx = supply_series.last_valid_index()
    
    if last_valid_idx is not None and last_valid_idx < len(df_pure) - 1:
        last_valid_supply = supply_series.loc[last_valid_idx]
        last_valid_date = df_pure.loc[last_valid_idx, 'date']
        
        # calculation for dates following last valid on-chain record
        for idx in range(last_valid_idx + 1, len(df_pure)):
            # validation of price availability
            if pd.isna(df_pure.loc[idx, 'btc_price']):
                continue
                
            dni_rozdiel = (df_pure.loc[idx, 'date'] - last_valid_date).days
            extrapolated_supply = last_valid_supply + (dni_rozdiel * 164.25)
            
            # forward fill of last valid realized price
            last_realized_price = df_pure['realized_price'].loc[:last_valid_idx].ffill().iloc[-1]
            
            # calculation of missing daily metrics
            df_pure.loc[idx, 'market_cap'] = df_pure.loc[idx, 'btc_price'] * extrapolated_supply
            df_pure.loc[idx, 'realized_cap'] = last_realized_price * extrapolated_supply
            df_pure.loc[idx, 'realized_price'] = last_realized_price

    # removal of temporary merge columns
    df_pure.drop(columns=['btc_price_latest', 'circulating_supply', 'realized_cap_latest', 'realized_price_historical'], errors='ignore', inplace=True)

    # removal of incomplete rows
    df_pure = df_pure.dropna(subset=['btc_price', 'realized_cap', 'realized_price'])

    # dynamic filtering based on config dates
    config_start_date = getattr(config, 'NUPL_START_DATE', None)
    if config_start_date:
        start_date = pd.to_datetime(config_start_date).normalize()
        df_pure = df_pure[df_pure['date'] >= start_date]

    config_end_date = getattr(config, 'NUPL_END_DATE', None)
    if config_end_date:
        end_date = pd.to_datetime(config_end_date).normalize()
        df_pure = df_pure[df_pure['date'] <= end_date]

    # exclusion of current day record
    dnesny_datum = pd.Timestamp.now().normalize()
    df_pure = df_pure[df_pure['date'] != dnesny_datum]
    
    df_pure = df_pure.copy()

    if df_pure.empty:
        print("-> [UPOZORNENIE] Po aplikovani filtrov neostali ziadne data. Graf nebude vykresleny.")
        return

    # temporary calculation of summary metrics
    df_pure['nupl_usd_total'] = df_pure['market_cap'] - df_pure['realized_cap']
    df_pure['nupl_ratio_total'] = (df_pure['nupl_usd_total'] / df_pure['market_cap']) * 100

    # formatting of text summary output
    last_row = df_pure.iloc[-1]
    last_date_str = last_row['date'].strftime('%Y-%m-%d')
    
    vystup_text = [
        "====================================================",
        f"POSLEDNE DOSTUPNE HODNOTY (K DATUMU: {last_date_str})",
        "====================================================",
        f"BTC Price:      ${last_row['btc_price']:,.2f}",
        f"NUPL (Relativny): {last_row['nupl_ratio_total']:.2f}%",
        f"NUPL (Absolutny): ${last_row['nupl_usd_total']:,.2f}",
        "===================================================="
    ]

    # terminal summary output
    print("\n" + "\n".join(vystup_text) + "\n")

    # export of summary text file
    summary_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_SUMMARY_DIR))
    os.makedirs(summary_dir, exist_ok=True)
    txt_path = os.path.join(summary_dir, f"{config.NUPL}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(vystup_text))
    print(f"-> [INFO] Summary ulozene do: {txt_path}")

    # calculation mode selection between relative percentage and absolute usd
    if relative_mode:
        print("-> [VYPOCET] Pocitam relativny NUPL v %...")
        # ratio calculation formula
        df_pure['nupl_metric'] = ((df_pure['market_cap'] - df_pure['realized_cap']) / df_pure['market_cap']) * 100
        y_label = 'Net Unrealized Profit / Loss (%)'
        title_label = 'Bitcoin: Net Unrealized Profit vs Loss (NUPL %)'
        formatter = plt.FuncFormatter(lambda x, loc: f"{int(x)}%")
    else:
        print("-> [VYPOCET] Pocitam absolutny Net P/L v USD...")
        df_pure['nupl_metric'] = df_pure['market_cap'] - df_pure['realized_cap']
        y_label = 'Network Net Profit / Loss (USD)'
        title_label = 'Bitcoin: Network Net Unrealized Profit vs Loss (USD)'
        formatter = plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x)))
    
    # separation of profit and loss areas for fill plot
    df_pure['plot_profit'] = df_pure['nupl_metric'].clip(lower=0)
    df_pure['plot_loss'] = df_pure['nupl_metric'].clip(upper=0)

    # rendering of nupl visual chart
    print("-> [GRAF] Vykreslujem Net Unrealized Profit/Loss graf...")
    
    fig, ax1 = plt.subplots(figsize=(15, 8))

    # left axis plot for profit and loss areas
    ax1.fill_between(df_pure['date'], df_pure['plot_profit'], 0, color='green', alpha=0.3, label='Net Profit')
    ax1.fill_between(df_pure['date'], df_pure['plot_loss'], 0, color='red', alpha=0.4, label='Net Loss (Kapitulacia)')
    
    # baseline reference line
    ax1.axhline(0, color='black', linestyle='-', alpha=0.5, linewidth=1.2)

    ax1.set_ylabel(y_label, color='black', fontsize=12)
    ax1.tick_params(axis='y', labelcolor='black')
    ax1.yaxis.set_major_formatter(formatter)
    ax1.grid(True, which='both', linestyle='--', alpha=0.3)

    if relative_mode:
        ax1.set_ylim(bottom=max(df_pure['plot_loss'].min() - 10, -100), top=min(df_pure['plot_profit'].max() + 10, 100))

    # right axis plot for logarithmic price and realized price
    ax2 = ax1.twinx()
    
    # btc market price series
    color_btc_chart = getattr(config, 'COLOR_FLUTTER_BTC', '#FF9900')
    ax2.plot(df_pure['date'], df_pure['btc_price'], color=color_btc_chart, linewidth=1.8, label='BTC Market Price', alpha=0.8)
    
    # realized price series
    color_realized_chart = getattr(config, 'COLOR_FLUTTER_REALIZED', '#00BCD4')
    ax2.plot(df_pure['date'], df_pure['realized_price'], color=color_realized_chart, linewidth=1.5, linestyle='--', label='Realized Price', alpha=0.8)
    
    # right axis formatting
    ax2.set_yscale('log')
    ax2.set_ylabel('BTC Price USD (Log scale)', color='black', fontsize=12)
    ax2.tick_params(axis='y', labelcolor='black')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"${int(x):,}"))

    # x axis date formatting
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.autofmt_xdate(rotation=45)

    plt.title(title_label, fontsize=14, fontweight='bold', pad=15)
    fig.tight_layout()
    
    # combined legend configuration
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)


    # saving output image
    graphs_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_GRAPHS_DIR))
    os.makedirs(graphs_dir, exist_ok=True)

    output_image_path = os.path.join(graphs_dir, "bitcoin_nupl_chart.png")
    print(f"-> [GRAF] Ukladam vysledny graf do: {output_image_path}")
    
    plt.savefig(output_image_path, dpi=300)
    plt.close()
    print("-> [KONIEC] Analyza uspesne dokoncena.")
    # database connection initialization
    conn = db_exporter.get_db_connection()
    try:
        # database payload preparation
        print("-> [DB] Pripravujem data pre Postgres DB export...")
        
        # conversion of dates to millisecond timestamps
        timestamps = (df_pure['date'].astype('int64') // 10**6).tolist()
        
        # extraction of latest row metrics
        aktualny_datum = last_date_str
        aktualna_cena = float(last_row['btc_price'])
        aktualna_realized_cena = float(last_row['realized_price'])
        aktualne_nupl_rel = float(last_row['nupl_ratio_total'])
        aktualne_nupl_abs = float(last_row['nupl_usd_total'])
        
        # extraction of latest fear and greed metric
        df_fng_today = df_fng[df_fng['date'] == last_row['date']]
        if not df_fng_today.empty:
            aktualny_fng = float(df_fng_today['fng'].iloc[0])
        else:
            aktualny_fng = 50.0

        # categorization of nupl market regime
        if aktualne_nupl_rel < 0:
            onchain_stav_nupl = "CAPITULATION (Negative NUPL)"
            label_color = getattr(config, 'COLOR_NUPL_CAPITULATION', '#FF0000')
        elif 0 <= aktualne_nupl_rel < 25:
            onchain_stav_nupl = "HOPE / FEAR"
            label_color = getattr(config, 'COLOR_NUPL_HOPE', '#FFA500')
        elif 25 <= aktualne_nupl_rel < 50:
            onchain_stav_nupl = "OPTIMISM / ANXIETY"
            label_color = getattr(config, 'COLOR_NUPL_OPTIMISM', '#FFFF00')
        elif 50 <= aktualne_nupl_rel < 75:
            onchain_stav_nupl = "BELIEF / DENIAL"
            label_color = getattr(config, 'COLOR_NUPL_BELIEF', '#00FF00')
        else:
            onchain_stav_nupl = "EUPHORIA / GREED"
            label_color = getattr(config, 'COLOR_NUPL_EUPHORIA', '#006400')

        # assembly of structured table output payload
        table_output_data = {
            "report_date": aktualny_datum,
            "rows": [
                {"key": "btc_price", "label": "Current Market Price", "raw_value": aktualna_cena, "display_value": f"${aktualna_cena:,.2f}"},
                {"key": "realized_price", "label": "Realized Price", "raw_value": aktualna_realized_cena, "display_value": f"${aktualna_realized_cena:,.2f}"},
                {"key": "nupl_relative", "label": "Relative NUPL Index", "raw_value": round(aktualne_nupl_rel, 2), "display_value": f"{aktualne_nupl_rel:.2f}%"},
                {"key": "fear_and_greed", "label": "Fear & Greed Sentiment", "raw_value": aktualny_fng, "display_value": f"{aktualny_fng:.0f}/100"},
                {"key": "nupl_status", "label": "STATISTICAL ON-CHAIN STATE", "raw_value": onchain_stav_nupl, "display_value": onchain_stav_nupl}
            ],
            "visual_meta": {
                "label_color_hex": label_color
            }
        }

        spojeny_vystup = "\n".join(vystup_text)
        model_version = getattr(config, 'MODEL_VERSION_NUPL', '1.0.0')

        # database export of price comparison widget
        print("-> [DB] Exportujem samostatny widget ceny BTC a Realized Price...")
        
        id_widget_cena = getattr(config, 'ID_WIDGET_NUPL_PRICE', 'current_btc_price_nupl')
        title_cena = getattr(config, 'WIDGET_NUPL_PRICE_TITLE', 'Bitcoin: Market vs Realized Price')
        subtitle_cena = getattr(config, 'WIDGET_NUPL_PRICE_SUBTITLE', 'Historical BTC price performance paired with network cost basis')
        color_btc = getattr(config, 'COLOR_FLUTTER_BTC', '#FF9900')
        color_realized = getattr(config, 'COLOR_FLUTTER_REALIZED', '#00BCD4')

        db_exporter.save_chart_document(conn, id_widget_cena, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
            "meta": {
                "title": title_cena, 
                "subtitle": subtitle_cena, 
                "primary_metric_name": "Market vs Realized", 
                "status_tags": ["price", "macro_models", "live"]
            },
            "chart_config": {
                "type": "MULTI_LINE", 
                "x_axis_type": "datetime", 
                "y_axis_config": {
                    "left": {
                        "label": "Price (USD)", 
                        "min": float(df_pure['btc_price'].min() * 0.95), 
                        "max": float(df_pure['btc_price'].max() * 1.05)
                    }, 
                    "right": None
                }
            },
            "chart_data": {
                "timestamps": timestamps, 
                "datasets": [
                    {
                        "label": "Market Price (BTC)", 
                        "axis": "left", 
                        "color": color_btc, 
                        "values": df_pure['btc_price'].round(2).tolist()
                    },
                    {
                        "label": "Realized Price", 
                        "axis": "left", 
                        "color": color_realized, 
                        "values": df_pure['realized_price'].round(2).tolist()
                    }
                ]
            },
            "ai_content": {
                "summary": f"Current BTC price is ${aktualna_cena:,.2f} while Realized price sits at ${aktualna_realized_cena:,.2f}.\n{spojeny_vystup}", 
                "model_version": model_version
            },
            "table_output": table_output_data
        }, has_access=True, is_premium=False)


        # database export of nupl oscillator widget
        print("-> [DB] Exportujem samostatny widget NUPL Indexu...")
        
        id_widget_nupl = getattr(config, 'ID_WIDGET_NUPL_OSCILLATOR', 'current_btc_nupl_oscillator')
        title_nupl = getattr(config, 'WIDGET_NUPL_OSCILLATOR_TITLE', 'Bitcoin: Net Unrealized Profit/Loss (NUPL)')
        subtitle_nupl = getattr(config, 'WIDGET_NUPL_OSCILLATOR_SUBTITLE', 'Relative ratio of total network unrealized profit and loss in %')
        color_nupl = getattr(config, 'COLOR_FLUTTER_NUPL', '#3498db')

        db_exporter.save_chart_document(conn, id_widget_nupl, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, {
            "meta": {
                "title": title_nupl, 
                "subtitle": subtitle_nupl, 
                "primary_metric_name": "NUPL (%)", 
                "status_tags": ["macro_onchain", "oscillator", "live"]
            },
            "chart_config": {
                "type": "OSCILLATOR", 
                "x_axis_type": "datetime", 
                "y_axis_config": {
                    "left": {
                        "label": "NUPL (%)", 
                        "min": float(df_pure['nupl_ratio_total'].min() - 5), 
                        "max": float(df_pure['nupl_ratio_total'].max() + 5)
                    }, 
                    "right": None
                }
            },
            "chart_data": {
                "timestamps": timestamps, 
                "datasets": [
                    {
                        "label": "NUPL Index (%)", 
                        "axis": "left", 
                        "color": color_nupl, 
                        "values": df_pure['nupl_ratio_total'].round(2).tolist()
                    }
                ]
            },
            "ai_content": {
                "summary": f"Global market state based on NUPL methodology: {onchain_stav_nupl} ({aktualne_nupl_rel:.2f}%).", 
                "model_version": model_version
            },
            "table_output": table_output_data
        }, has_access=True, is_premium=False)

        print("-> [KONIEC] Vsetky historicke aj nove data boli uspesne ulozene do oboch widgetov v DB.")

    except Exception as e:
        print(f"[EXPORT CRITICAL ERROR] Zlyhal export oscilatora do DB: {e}")
    finally:
        conn.close()
        print("-> [POSTGRES] Spojenie s databazou bolo zatvorene.")

# execution entry point
if __name__ == "__main__":
    run_integrated_onchain_analysis(parquet_onchain_path, parquet_fng_path,DAILY_1D_PARQUET_PATH,manual_txt_path,relative_mode=True)