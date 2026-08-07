import os
import sys
import json
import datetime
import importlib.util
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# system path setup for config.py import
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
tools_dir = os.path.join(project_root, "tools")
sys.path.append(tools_dir)

import config

# safe direct import of db_exporter.py via absolute path
db_exporter_path = os.path.join(tools_dir, "db_exporter.py")
if not os.path.exists(db_exporter_path):
    raise FileNotFoundError(f"Kriticka chybe: Subor {db_exporter_path} sa nenasiel!")

spec = importlib.util.spec_from_file_location("db_exporter", db_exporter_path)
db_exporter = importlib.util.module_from_spec(spec)
sys.modules["db_exporter"] = db_exporter
spec.loader.exec_module(db_exporter)

output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)

abs_parquet_path = os.path.join(output_dir, config.FILENAME_DAY)


def run_integrated_power_law_analysis(parquet_path):
    print(f"-> [START] Nacitavam 1-dnove data z Parquet: {parquet_path}")
    
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"Chyba: Subor {parquet_path} neexistuje.")
        
    df_raw = pd.read_parquet(parquet_path)
    df = pd.DataFrame()
    df['date'] = pd.to_datetime(df_raw['datum'])
    df['close'] = df_raw['cena_btc_usdt'].astype(float)
    df = df[['date', 'close']].sort_values('date').reset_index(drop=True)

    # removal of current unclosed day
    dnesny_den = pd.Timestamp(datetime.date.today())
    df = df[df['date'] < dnesny_den].copy()

    # power-law and residuals mathematics
    genesis_date = pd.to_datetime(config.GENESIS_DATE_STR)
    df['days_since_genesis'] = (df['date'] - genesis_date).dt.days

    log_days = np.log10(df['days_since_genesis'])
    df['actual_log_price'] = np.log10(df['close'])

    slope, intercept = np.polyfit(log_days, df['actual_log_price'], 1)
    
    df['expected_log_price'] = intercept + slope * log_days
    df['residual'] = df['actual_log_price'] - df['expected_log_price']
    std_residual = df['residual'].std()
    df['z_score'] = df['residual'] / std_residual

    # calculation of forward returns
    for nazov, dni in config.HORIZONS.items():
        df[f'return_{nazov}'] = (df['close'].shift(-dni) / df['close']) - 1

    # extraction of current values for today
    aktualne_z_score = df['z_score'].iloc[-1]
    aktualna_cena = df['close'].iloc[-1]
    aktualny_datum = df['date'].iloc[-1].strftime('%Y-%m-%d')

    # preparation of structure for recalculation based on z-score
    df_sorted = df.sort_values('z_score').copy()
    
    # calculation of rolling median for sorted z-scores across horizons
    for nazov in config.HORIZONS.keys():
        df_sorted[f'curve_median_{nazov}'] = df_sorted[f'return_{nazov}'].rolling(
            window=config.ROLLING_MEDIAN_WINDOW, center=True, min_periods=1
        ).median()

    # restoration of chronological order for database storage
    df_final_series = df_sorted.sort_values('date').copy()

    # extraction of updated values from chronologically sorted dataset
    aktualne_z_score = df_final_series['z_score'].iloc[-1]
    aktualna_cena = df_final_series['close'].iloc[-1]
    aktualny_datum = df_final_series['date'].iloc[-1].strftime('%Y-%m-%d')

    # initialization of database connection and incremental backfill check
    conn = db_exporter.get_db_connection()
    try:
        db_exporter.init_database(conn)
        
        # detection of missing dates based on unified key
        posledny_db_datum = db_exporter.get_last_recorded_date(conn, "pl_z_score")
        
        if posledny_db_datum is None:
            print("-> [DB BACKFILL] V DB nie su ziadne data. Spustam kompletny backfill...")
            df_missing = df_final_series.copy()
        else:
            posledny_db_ts = pd.to_datetime(posledny_db_datum)
            df_missing = df_final_series[df_final_series['date'] > posledny_db_ts].copy()
            print(f"-> [DB CHECK] Posledny zapis v DB je z: {posledny_db_ts.strftime('%Y-%m-%d')}.")
            print(f"-> [DB CHECK] Doplnam: {len(df_missing)} chybajucich dni.")

        # export of all metrics to database
        backfill_counter = 0
        for idx, row in df_missing.iterrows():
            m_date_str = row['date'].strftime('%Y-%m-%d')
            
            # daily baseline values
            db_exporter.save_metric_value(conn, m_date_str, "btc_price", row['close'])
            db_exporter.save_metric_value(conn, m_date_str, "pl_z_score", row['z_score'])
            
            # export of calculated medians for current z-score
            for horizont in config.HORIZONS.keys():
                median_val = row[f'curve_median_{horizont}']
                if pd.notna(median_val):
                    db_exporter.save_metric_value(conn, m_date_str, f"pl_median_{horizont}", median_val)
                    
            backfill_counter += 1

        if backfill_counter > 0:
            print(f"-> [POSTGRES] Úspešne dopísaných {backfill_counter} dní vrátane stat. mediánov.")

        # filtering of history bucket for current state
        z_min = aktualne_z_score - config.BUCKET_WIDTH
        z_max = aktualne_z_score + config.BUCKET_WIDTH
        bucket_df = df_final_series[(df_final_series['z_score'] >= z_min) & (df_final_series['z_score'] <= z_max)].copy()

        vystup_text = [
            "="*70,
            f" ANALYZA HISTORICKEHO KOSA (HISTORY BUCKET) PRE Z-SCORE ({aktualny_datum})",
            "="*70,
            f"Aktualne Z-Score odchylka: {aktualne_z_score:.2f}",
            f"Aktualna cena BTC: ${aktualna_cena:,.2f}",
            f"Rozsah kosa (Z-Score): od {z_min:.2f} do {z_max:.2f}",
            f"Pocet historickych dni (pozorovani) in tohto kosi: {len(bucket_df)}",
            "-" * 70
        ]

        tabulka_dat = {h: {} for h in config.HORIZON_COLUMNS_ORDER}
        db_json_percentiles = {h: {} for h in config.HORIZON_COLUMNS_ORDER}

        for h in config.HORIZON_COLUMNS_ORDER:
            ciste_data = bucket_df[f'return_{h}'].dropna()
            if len(ciste_data) > 0:
                for p in config.PERCENTILES:
                    hodnota_percentilu = np.percentile(ciste_data, p)
                    tabulka_dat[h][p] = f"{hodnota_percentilu * 100:+.1f}%"
                    db_json_percentiles[h][str(p)] = float(round(hodnota_percentilu, 4))
            else:
                for p in config.PERCENTILES:
                    tabulka_dat[h][p] = "N/A"
                    db_json_percentiles[h][str(p)] = None

        header_str = f"{'PERCENTIL':<13} | " + " | ".join([f"{h:<8}" for h in config.HORIZON_COLUMNS_ORDER])
        vystup_text.append(header_str)
        vystup_text.append("-" * 70)

        for p in config.PERCENTILES:
            row_str = f"{p}. percentil | "
            for h in config.HORIZON_COLUMNS_ORDER:
                row_str += f"{tabulka_dat[h][p]:<8} | "
            vystup_text.append(row_str.rstrip(" | "))

        vystup_text.append("=" * 70)
        print("\n" + "\n".join(vystup_text) + "\n")

        # generation of matrix structure for flutter
        
        # definition of table columns for flutter interface
        table_columns = ["Percentil"] + [str(h) for h in config.HORIZON_COLUMNS_ORDER]
        
        # generation of matrix rows
        table_rows = []
        for p in config.PERCENTILES:
            row_data = {
                "percentile": int(p),
                "label": f"{p}. percentil",
                "horizons": {}
            }
            
            for h in config.HORIZON_COLUMNS_ORDER:
                raw_val = db_json_percentiles[h][str(p)]
                row_data["horizons"][str(h)] = {
                    "raw_value": raw_val,
                    "display_value": tabulka_dat[h][p]
                }
                
            table_rows.append(row_data)

        # structure layout for daily charts database
        table_output_data = {
            "report_date": aktualny_datum,
            "meta": {
                "current_z_score": float(aktualne_z_score),
                "current_btc_price": float(aktualna_cena),
                "bucket_z_min": float(z_min),
                "bucket_z_max": float(z_max),
                "observations_count": int(len(bucket_df))
            },
            "table_structure": {
                "columns": table_columns,
                "rows": table_rows
            }
        }

        summary_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_SUMMARY_DIR))
        os.makedirs(summary_dir, exist_ok=True)
        txt_path = os.path.join(summary_dir, f"{config.POWER_LAW_MULTI_HORIZONTS_FILENAME}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vystup_text))


        # rendering of chart visualization
        plt.figure(figsize=config.GRAPH_SIZE_POWER_LAW, facecolor='#0d1117')
        ax = plt.gca()
        ax.set_facecolor('#0d1117')
        df_sorted = df.sort_values('z_score').copy()
        plot_365 = df_sorted.dropna(subset=['return_365D'])
        ax.scatter(plot_365['z_score'], plot_365['return_365D'], c=plot_365['date'].dt.year, cmap='viridis', alpha=0.12, s=10, label='Historicke body (365D podklad)')
        
        db_json_medians = {}
        
        # preparation of datasets for flutter graph engine
        flutter_x_z_scores = [round(x, 2) for x in np.arange(-2.0, 2.5, 0.01)]
        flutter_datasets = []

        for nazov, dni in config.HORIZONS.items():
            temp_df = df_sorted.dropna(subset=[f'return_{nazov}']).copy()
            temp_df[f'median_{nazov}'] = temp_df[f'return_{nazov}'].rolling(window=config.ROLLING_MEDIAN_WINDOW, center=True).median()
            temp_df = temp_df.dropna(subset=[f'median_{nazov}'])
            
            if not temp_df.empty:
                idx_najblizsie = (temp_df['z_score'] - aktualne_z_score).abs().idxmin()
                aktualny_median_val = temp_df.loc[idx_najblizsie, f'median_{nazov}']
                percent_str = f"+{aktualny_median_val*100:.1f}%" if aktualny_median_val >= 0 else f"{aktualny_median_val*100:.1f}%"
                label_text = f'Median za {nazov:4} (Dnes: {percent_str})'
                db_json_medians[nazov] = float(round(aktualny_median_val, 4))
                
                # mapping of y values to unified x-axis
                flutter_y_values = []
                for x_val in flutter_x_z_scores:
                    idx_x = (temp_df['z_score'] - x_val).abs().idxmin()
                    y_val = temp_df.loc[idx_x, f'median_{nazov}']
                    flutter_y_values.append(float(round(y_val, 4)) if pd.notna(y_val) else None)
            else:
                label_text = f'Median za {nazov:4} (Dnes: N/A)'
                db_json_medians[nazov] = None
                flutter_y_values = [None] * len(flutter_x_z_scores)
            
            # dataset addition to flutter payload
            flutter_datasets.append({
                "label": f"Median {nazov}",
                "axis": "left",
                "color": config.TREND_COLORS.get(nazov, "#ffffff"),
                "values": flutter_y_values
            })

            ax.plot(temp_df['z_score'], temp_df[f'median_{nazov}'], color=config.TREND_COLORS[nazov], linewidth=2.5, label=label_text)

        ax.axvline(
            x=aktualne_z_score, 
            color='#ffffff', 
            linestyle='--', 
            linewidth=1.5, 
            label=f'Aktualne BTC Z-Score: {aktualne_z_score:+.2f} ({aktualny_datum})'
        )
        
        ax.set_xlabel('Power-law Z-score', color='white', fontsize=12)
        ax.set_ylabel('Realized Forward Return (Percentualny zisk 1.0 = 100%)', color='white', fontsize=12)
        ax.set_title('Bitcoin Power-Law: Historicke mediany navratnosti pre aktualne Z-Score', color='white', fontsize=14, fontweight='bold', pad=15)
        ax.set_ylim(config.GRAPH_YLIM_MIN, config.GRAPH_YLIM_MAX)
        ax.tick_params(colors='white')
        ax.grid(True, color='#21262d', linestyle=':')
        plt.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='white', loc='upper right', prop={'family': 'monospace', 'size': 10})
        plt.tight_layout()

        graphs_dir = os.path.abspath(os.path.join(config.get_project_root(), config.OUTPUT_GRAPHS_DIR))
        os.makedirs(graphs_dir, exist_ok=True)
        graph_path = os.path.join(graphs_dir, f"{config.POWER_LAW_MULTI_HORIZONTS_FILENAME}.png")
        plt.savefig(graph_path, dpi=300)
        plt.close()
        print(f"-> Novy graf bol uspesne ulozeny do: {graph_path}")


        # export of flutter widget payload
        id_widget = config.ID_WIDGET_MULTI_HORIZONS


        # extraction of smoothed curve value for latest entry
        posledny_riadok = df_final_series.iloc[-1]
        
        grafovy_median_365d = posledny_riadok['curve_median_365D']
        
        # formatting of return percentage string
        if pd.notna(grafovy_median_365d):
            grafovy_median_pct = grafovy_median_365d * 100
            median_365d_text = f"+{grafovy_median_pct:.1f}%" if grafovy_median_pct >= 0 else f"{grafovy_median_pct:.1f}%"
        else:
            median_365d_text = "N/A"

        doc_data = {
            "meta": {
                "title": config.WIDGET_MULTI_TITLE,
                "subtitle": config.WIDGET_MULTI_SUBTITLE,
                "current_price": float(aktualna_cena),
                "current_z_score": float(round(aktualne_z_score, 3)),
                "bucket_range": {
                    "min": float(round(z_min, 3)),
                    "max": float(round(z_max, 3))
                },
                "observations_in_bucket": int(len(bucket_df))
            },
            # graph engine configuration
            "chart_config": {
                "type": config.ChartType.POWER_LAW_RETURNS.value,
                "x_axis_type": "z_score",
                "y_axis_config": {
                    "left": {
                        "label": "Forward Return",
                        "min": float(config.GRAPH_YLIM_MIN),
                        "max": float(config.GRAPH_YLIM_MAX)
                    },
                    "right": None
                }
            },
            # payload generation for charts
            "chart_data": {
                "x_values": flutter_x_z_scores,
                "datasets": flutter_datasets
            },
            # reference datasets for structural tables
            "analysis_data": {
                "horizons": config.HORIZON_COLUMNS_ORDER,
                "percentiles": config.PERCENTILES,
                "matrix": db_json_percentiles,
                "current_medians": db_json_medians
            },
            "ai_content": {
                "summary": f"Pre aktualne Power-Law Z-Score ({aktualne_z_score:.2f}) vykazuje historicky kos median 365-dnovej navratnosti na urovni {median_365d_text}.",
                "model_version": config.MODEL_VERSION_POWER_LAW_MULTI
            },
            "table_output": table_output_data
        }

        db_exporter.save_chart_document(conn, id_widget, aktualny_datum, config.WIDGET_CRYPTO_CATEGORY, doc_data,has_access=True, is_premium=False)
        print(f"-> [POSTGRES] Multi-Horizon widget export uspesne dokonceny.")


    except Exception as e:
        print(f"[EXPORT CRITICAL ERROR] Zlyhal export do DB v multi-horizontoch: {e}")
    finally:
        conn.close()
        print("-> [POSTGRES] Spojenie s databazou bolo uzatvorene.")


if __name__ == "__main__":
    run_integrated_power_law_analysis(abs_parquet_path)