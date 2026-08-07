import os
import sys
import json
import datetime
import importlib.util
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.collections import LineCollection

# setup of system path for tools directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
tools_dir = os.path.join(project_root, "tools")
sys.path.append(tools_dir)

import config

# safe direct import of db_exporter
db_exporter_path = os.path.join(tools_dir, "db_exporter.py")
if not os.path.exists(db_exporter_path):
    raise FileNotFoundError(f"Kriticka chyba: Subor {db_exporter_path} sa nenasiel!")

spec = importlib.util.spec_from_file_location("db_exporter", db_exporter_path)
db_exporter = importlib.util.module_from_spec(spec)
sys.modules["db_exporter"] = db_exporter
spec.loader.exec_module(db_exporter)

# parquet output directory path
output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

abs_parquet_path = os.path.join(output_dir, config.FILENAME_DAY)


def run_integrated_oscillator_analysis(parquet_path):
    print(f"-> [START] Nacitavam 1-dnove data pre Oscilator z: {parquet_path}")
    
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"Chyba: Subor {parquet_path} neexistuje.")

    df_raw = pd.read_parquet(parquet_path)
    df = pd.DataFrame()
    df['date'] = pd.to_datetime(df_raw['datum'])
    df['close'] = df_raw['cena_btc_usdt'].astype(float)
    df = df[['date', 'close']].sort_values('date').reset_index(drop=True)

    # exclusion of today's unfinished candle
    dnesny_den = pd.Timestamp(datetime.date.today())
    df = df[df['date'] < dnesny_den].copy()

    # power-law modeling mathematics across history
    genesis_date = pd.to_datetime(config.GENESIS_DATE_STR)
    df['days_since_genesis'] = (df['date'] - genesis_date).dt.days

    log_days = np.log10(df['days_since_genesis'])
    df['actual_log_price'] = np.log10(df['close'])

    slope, intercept = np.polyfit(log_days, df['actual_log_price'], 1)
    r_squared = np.corrcoef(log_days, df['actual_log_price'])[0, 1] ** 2

    df['expected_log_price'] = intercept + slope * log_days
    df['fair_value'] = 10 ** df['expected_log_price']
    df['residual'] = df['actual_log_price'] - df['expected_log_price']
    std_residual = df['residual'].std()
    df['z_score'] = df['residual'] / std_residual

    df['plus_2sigma'] = 10 ** (df['expected_log_price'] + 2 * std_residual)
    df['minus_2sigma'] = 10 ** (df['expected_log_price'] - 2 * std_residual)

    # extraction of current day metrics
    print_cena = df['close'].iloc[-1]
    print_z_score = df['z_score'].iloc[-1]
    print_fair_value = df['fair_value'].iloc[-1]
    print_plus_2sigma = df['plus_2sigma'].iloc[-1]
    print_minus_2sigma = df['minus_2sigma'].iloc[-1]
    print_datum = df['date'].iloc[-1].strftime('%Y-%m-%d')

    halvings = [pd.to_datetime(d) for d in config.HALVING_DATES]

    if print_z_score > config.Z_SCORE_LIMIT_STRONG_OVERVALUED:
        stav_text = config.STATUS_STRONG_OVERVALUED
        label_color = config.COLOR_STRONG_OVERVALUED

    halvings = [pd.to_datetime(d) for d in config.HALVING_DATES]

    # database initialization and incremental backfill of oscillator metrics
    conn = db_exporter.get_db_connection()
    try:
        db_exporter.init_database(conn)
        
        # detection of missing daily records
        posledny_db_datum = db_exporter.get_last_recorded_date(conn, "pl_oscillator_z")
        
        if posledny_db_datum is None:
            print("-> [DB BACKFILL] V DB nie su ziadne data pre Oscilator. Spustam kompletny backfill...")
            df_missing = df.copy()
        else:
            # type conversion of SQL date to pandas timestamp for comparison
            posledny_db_ts = pd.to_datetime(posledny_db_datum)
            df_missing = df[df['date'] > posledny_db_ts].copy()
            print(f"-> [DB CHECK] Posledny zapis v DB je z: {posledny_db_ts.strftime('%Y-%m-%d')}.")
            print(f"-> [DB CHECK] Doplnam: {len(df_missing)} chybajucich dni pre oscilator.")

        # persistence loop for missing history in time series
        backfill_counter = 0
        for idx, row in df_missing.iterrows():
            m_date_str = row['date'].strftime('%Y-%m-%d')
            db_exporter.save_metric_value(conn, m_date_str, "pl_oscillator_z", row['z_score'])
            db_exporter.save_metric_value(conn, m_date_str, "pl_fair_value", row['fair_value'])
            db_exporter.save_metric_value(conn, m_date_str, "pl_plus_2sigma", row['plus_2sigma'])
            db_exporter.save_metric_value(conn, m_date_str, "pl_minus_2sigma", row['minus_2sigma'])
            backfill_counter += 1

        if backfill_counter > 0:
            print(f"-> [POSTGRES] Uspesne dopisanych {backfill_counter} dni do {config.DB_TABLE_TIME_SERIES}.")

        # re-extraction of current status values
        print_cena = df['close'].iloc[-1]
        print_z_score = df['z_score'].iloc[-1]
        print_fair_value = df['fair_value'].iloc[-1]
        print_plus_2sigma = df['plus_2sigma'].iloc[-1]
        print_minus_2sigma = df['minus_2sigma'].iloc[-1]
        print_datum = df['date'].iloc[-1].strftime('%Y-%m-%d')

        if print_z_score > config.Z_SCORE_LIMIT_STRONG_OVERVALUED:
            stav_text = config.STATUS_STRONG_OVERVALUED
            label_color = config.COLOR_STRONG_OVERVALUED
        elif config.Z_SCORE_LIMIT_OVERVALUED_LOW < print_z_score <= config.Z_SCORE_LIMIT_OVERVALUED_HIGH:
            stav_text = config.STATUS_OVERVALUED
            label_color = config.COLOR_OVERVALUED
        elif config.Z_SCORE_LIMIT_NEUTRAL_LOW <= print_z_score <= config.Z_SCORE_LIMIT_NEUTRAL_HIGH:
            stav_text = config.STATUS_NEUTRAL
            label_color = config.COLOR_NEUTRAL
        elif config.Z_SCORE_LIMIT_UNDERVALUED_LOW <= print_z_score < config.Z_SCORE_LIMIT_UNDERVALUED_HIGH:
            stav_text = config.STATUS_UNDERVALUED
            label_color = config.COLOR_UNDERVALUED
        else:
            stav_text = config.STATUS_STRONG_UNDERVALUED
            label_color = config.COLOR_STRONG_UNDERVALUED

        # formatting of text report for local storage
        vystup_text = [
            "="*60,
            f" STATUS BITCOIN POWER-LAW OSCILATORA ({print_datum})",
            "="*60,
            f"Aktualna cena na Binance   : ${print_cena:,.2f}",
            f"Modelova ferova cena       : ${print_fair_value:,.2f}",
            f"Horne pasmo (+2 odchylka)  : ${print_plus_2sigma:,.2f}",
            f"Spodne pasmo (-2 odchylka) : ${print_minus_2sigma:,.2f}",
            f"Aktualne Z-Score odchylka  : {print_z_score:+.2f}",
            f"VYHODNOTENIE TRHU          : {stav_text}",
            "="*60
        ]
        print("\n" + "\n".join(vystup_text) + "\n")

        # generation of structured table output
        table_output_data = {
            "report_date": print_datum,
            "rows": [
                {
                    "key": "binance_price",
                    "label": "Aktualna cena na Binance",
                    "raw_value": float(print_cena),
                    "display_value": f"${print_cena:,.2f}"
                },
                {
                    "key": "model_fair_value",
                    "label": "Modelova ferova cena",
                    "raw_value": float(print_fair_value),
                    "display_value": f"${print_fair_value:,.2f}"
                },
                {
                    "key": "power_law_plus_2sigma",
                    "label": "Horne pasmo (+2 odchylka)",
                    "raw_value": float(print_plus_2sigma),
                    "display_value": f"${print_plus_2sigma:,.2f}"
                },
                {
                    "key": "power_law_minus_2sigma",
                    "label": "Spodne pasmo (-2 odchylka)",
                    "raw_value": float(print_minus_2sigma),
                    "display_value": f"${print_minus_2sigma:,.2f}"
                },
                {
                    "key": "power_law_z_score",
                    "label": "Aktualne Z-Score odchylka",
                    "raw_value": float(print_z_score),
                    "display_value": f"{print_z_score:+.2f}"
                },
                {
                    "key": "market_evaluation",
                    "label": "VYHODNOTENIE TRHU",
                    "raw_value": stav_text,
                    "display_value": stav_text
                }
            ],
            "visual_meta": {
                "market_status_raw": stav_text,
                "status_tag": "power_law"
            }
        }

        summary_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_SUMMARY_DIR))
        os.makedirs(summary_dir, exist_ok=True)
        txt_path = os.path.join(summary_dir, f"{config.POWER_LAW_OSCILLATOR_FILENAME}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vystup_text))
        print(f"-> Textovy sumar bol uspesne ulozeny do: {txt_path}")

        # rendering of primary price and power-law chart
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=config.GRAPH_SIZE_OSCILLATOR, sharex=True, facecolor='black')
        for ax in [ax1, ax2]:
            ax.set_facecolor('black')
            ax.tick_params(colors='white', labelsize=10)
            ax.grid(True, color='#262626', linestyle='-', linewidth=0.5)

        ax1.set_yscale('log')
        ax1.set_title(f'Bitcoin Power Law [$R^2 = {r_squared:.4f}$]', color='white', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Price (USD)', color='white', fontsize=11)

        ax1.plot(df['date'], df['fair_value'], color='#e1b12c', linewidth=2.5, label=f'Fair Value  (Dnes: ${print_fair_value:,.2f})')
        ax1.plot(df['date'], df['plus_2sigma'], color='#c0392b', linestyle='--', linewidth=1, label=f'+2σ Band (Dnes: ${print_plus_2sigma:,.2f})')
        ax1.plot(df['date'], df['minus_2sigma'], color='#16a085', linestyle='--', linewidth=1, label=f'-2σ Band (Dnes: ${print_minus_2sigma:,.2f})')

        df['date_float'] = mdates.date2num(df['date'])
        points = np.array([df['date_float'].values, df['close'].values]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        norm = plt.Normalize(-2.0, 2.0)
        lc = LineCollection(segments, cmap='RdYlGn', norm=norm, linewidths=2)
        lc.set_array(df['z_score'].values)
        line = ax1.add_collection(lc)
        ax1.xaxis_date()

        cbar_ax = fig.add_axes([0.92, 0.55, 0.015, 0.33])
        cbar = fig.colorbar(line, cax=cbar_ax)
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
        ax1.legend(facecolor='#111111', edgecolor='#333333', labelcolor='white', loc='lower right', prop={'family': 'monospace', 'size': 9})
        ax1.text(0.95, 0.30, f"STAV: {stav_text}\nZ-SCORE: {print_z_score:+.2f}", color='white', fontsize=10, fontweight='bold', bbox=dict(facecolor=label_color, alpha=0.85, edgecolor='black', boxstyle='round,pad=0.5'), transform=ax1.transAxes, ha='right', va='top')

        # rendering of secondary z-score deviation chart
        ax2.set_title('Deviation from Trend (Z-Score)', color='white', fontsize=12)
        ax2.set_ylabel('Z-Score', color='white', fontsize=11)
        ax2.set_ylim(-3.5, 3.5)
        ax2.plot(df['date'], df['z_score'], color='white', linewidth=1)
        ax2.fill_between(df['date'], df['z_score'], 0, where=(df['z_score'] >= 0), color='green', alpha=0.7, interpolate=True)
        ax2.fill_between(df['date'], df['z_score'], 0, where=(df['z_score'] < 0), color='brown', alpha=0.7, interpolate=True)
        ax2.axhline(y=0, color='#e1b12c', linestyle='-', linewidth=1.5)
        ax2.axhline(y=2, color='#c0392b', linestyle='--', linewidth=1)
        ax2.axhline(y=-2, color='#16a085', linestyle='--', linewidth=1)
        ax2.text(0.95, 0.90, f"CENA: ${print_cena:,.2f}", color='white', fontsize=10, fontweight='bold', bbox=dict(facecolor='#222222', alpha=0.85, edgecolor='white', boxstyle='round,pad=0.5'), transform=ax2.transAxes, ha='right', va='top')

        for h_date in halvings:
            if h_date >= df['date'].min():
                ax1.axvline(x=h_date, color='#888888', linestyle='-', linewidth=0.8, alpha=0.5)
                ax2.axvline(x=h_date, color='#e1b12c', linestyle='-', linewidth=1, alpha=0.6)

        ax2.set_xlim(df['date'].min(), df['date'].max())
        plt.subplots_adjust(left=0.08, right=0.88, top=0.93, bottom=0.05, hspace=0.25)

        graphs_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_GRAPHS_DIR))
        os.makedirs(graphs_dir, exist_ok=True)
        graph_path = os.path.join(graphs_dir, f"{config.POWER_LAW_OSCILLATOR_FILENAME}.png")
        plt.savefig(graph_path, dpi=300, facecolor='black')
        plt.close()
        print(f"-> Novy korigovany graf bol ulozeny do '{graph_path}'.")

        # preparation of time series subset for mobile widgets
        if config.FLUTTER_CHART_SNAPSHOT_DAYS is None:
            df_chart = df.copy()
        else:
            df_chart = df.tail(config.FLUTTER_CHART_SNAPSHOT_DAYS).copy()
            
        df_chart['date'] = pd.to_datetime(df_chart['date'])
        timestamps = [int(dt.to_pydatetime().timestamp()) for dt in df_chart['date']]

        # document generation for price vs trend widget
        id_g1 = config.ID_WIDGET_PL_PRICE_TREND
        doc_g1 = {
            "meta": {
                "title": config.WIDGET_PL_PRICE_TITLE,
                "subtitle": config.WIDGET_PL_PRICE_SUBTITLE,
                "primary_metric_name": "BTC Price",
                "status_tags": ["macro", "regression", "bands"],
                "market_status": stav_text,
                "r_squared": float(round(r_squared, 4)),
                "current_stats": {
                    "price": float(print_cena),
                    "fair_value": float(round(print_fair_value, 2)),
                    "plus_2sigma": float(round(print_plus_2sigma, 2)),
                    "minus_2sigma": float(round(print_minus_2sigma, 2))
                }
            },
            "chart_config": {
                "type": config.ChartType.MULTI_AXIS_LOG,
                "x_axis_type": "datetime",
                "y_axis_config": {
                    "left": {
                        "label": "Price (USD)",
                        "min": float(df_chart['minus_2sigma'].min() * 0.9),
                        "max": float(df_chart['plus_2sigma'].max() * 1.1)
                    },
                    "right": None
                }
            },
            "chart_data": {
                "timestamps": timestamps,
                "datasets": [
                    { "label": "Actual Price", "axis": "left", "color": "#FF9900", "values": df_chart['close'].round(2).tolist() },
                    { "label": "Fair Value", "axis": "left", "color": config.COLOR_FLUTTER_OSCILLATOR_LINE, "values": df_chart['fair_value'].round(2).tolist() },
                    { "label": "+2σ Band", "axis": "left", "color": "#c0392b", "values": df_chart['plus_2sigma'].round(2).tolist() },
                    { "label": "-2σ Band", "axis": "left", "color": "#16a085", "values": df_chart['minus_2sigma'].round(2).tolist() }
                ]
            },
            "ai_content": {
                "summary": f"Bitcoin sa obchoduje za ${print_cena:,.2f} voci ferovej modelovej cene ${print_fair_value:,.2f}.\n{vystup_text}",
                "model_version": config.MODEL_VERSION_POWER_LAW_OSCILLATOR
            },
            "table_output": table_output_data
        }
        db_exporter.save_chart_document(conn, id_g1, print_datum, config.WIDGET_CRYPTO_CATEGORY, doc_g1, has_access=True, is_premium=False)

        # document generation for z-score deviation widget
        id_g2 = config.ID_WIDGET_PL_DEVIATION_Z
        doc_g2 = {
            "meta": {
                "title": config.WIDGET_PL_DEV_TITLE,
                "subtitle": config.WIDGET_PL_DEV_SUBTITLE,
                "primary_metric_name": "Oscillator Z-Score",
                "status_tags": ["macro", "oscillator", "deviation"],
                "market_status": stav_text,
                "current_z_score": float(round(print_z_score, 3))
            },
            "chart_config": {
                "type": config.ChartType.OSCILLATOR,
                "x_axis_type": "datetime",
                "y_axis_config": {
                    "left": {
                        "label": "Z-Score",
                        "min": -3.5,
                        "max": 3.5
                    },
                    "right": None
                }
            },
            "chart_data": {
                "timestamps": timestamps,
                "datasets": [
                    { "label": "Z-Score Deviation", "axis": "left", "color": config.COLOR_FLUTTER_OSCILLATOR_LINE, "values": df_chart['z_score'].round(3).tolist() }
                ]
            },
            "ai_content": {
                "summary": f"Aktualna odchylka od mocninoveho zakona dosahuje hodnotu {print_z_score:+.2f}, co trh radi do stavu: {stav_text}.",
                "model_version": config.MODEL_VERSION_POWER_LAW_OSCILLATOR
            }
        }
        db_exporter.save_chart_document(conn, id_g2, print_datum, config.WIDGET_CRYPTO_CATEGORY, doc_g2, has_access=True, is_premium=False)
        print(f"-> [POSTGRES] Oba Power-Law widgety boli samostatne zapisane do daily_charts.")

    except Exception as e:
        print(f"[EXPORT CRITICAL ERROR] Zlyhal export oscilatora do DB: {e}")
    finally:
        conn.close()
        print("-> [POSTGRES] Spojenie s databazou bolo zatvorene.")


if __name__ == "__main__":
    run_integrated_oscillator_analysis(abs_parquet_path)