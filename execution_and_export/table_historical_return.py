import os
import sys
import datetime
import importlib.util
import numpy as np
import pandas as pd

# configuration and paths setup
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

START_YEAR = config.START_YEAR  

data_dir = os.path.join(project_root, "data")
ONCHAIN_PARQUET_PATH = os.path.join(data_dir, "BTC_onchain.parquet")

output_dir = os.path.abspath(os.path.join(config.get_project_root(), config.PARQUET_OUTPUT_PATH))
if output_dir.endswith('.parquet'):
    output_dir = os.path.dirname(output_dir)
DAILY_1D_PARQUET_PATH = os.path.join(output_dir, config.FILENAME_DAY)


def load_and_merge_data():
    """
    Merging of spot and historical on-chain datasets.
    Cleaning of timeline to daily boundaries for index joining.
    """
    print("-> [DATA] Nacitavam spotove data z BTC_1d.parquet...")
    df_1d_raw = pd.read_parquet(DAILY_1D_PARQUET_PATH)
    df_1d = pd.DataFrame()
    df_1d['date'] = pd.to_datetime(df_1d_raw['datum']).dt.tz_localize(None).dt.floor('D')
    df_1d['close_1d'] = df_1d_raw['cena_btc_usdt'].astype(float)
    df_1d = df_1d.dropna(subset=['close_1d']).drop_duplicates('date').set_index('date')

    print("-> [DATA] Nacitavam on-chain data z BTC_onchain.parquet...")
    df_onchain = pd.read_parquet(ONCHAIN_PARQUET_PATH)
    df_oc = pd.DataFrame()
    df_oc['date'] = pd.to_datetime(df_onchain['date']).dt.tz_localize(None).dt.floor('D')
    df_oc['close_oc'] = df_onchain['ReferenceRateUSD'].fillna(df_onchain['PriceUSD']).astype(float)
    df_oc = df_oc.dropna(subset=['close_oc']).drop_duplicates('date').set_index('date')

    # index joining without microsecond offsets
    all_indices = df_1d.index.union(df_oc.index)
    df_combined = pd.DataFrame(index=all_indices)
    df_combined['close_1d'] = df_1d['close_1d']
    df_combined['close_oc'] = df_oc['close_oc']
    
    # priority assignment to spot price with on-chain fallback for history
    df_combined['close'] = df_combined['close_1d'].fillna(df_combined['close_oc'])
    
    df_combined = df_combined.reset_index().rename(columns={'index': 'date'})
    df_combined = df_combined.dropna(subset=['close'])
    df_combined = df_combined.sort_values('date').reset_index(drop=True)
    
    dnesny_den = pd.Timestamp(datetime.date.today())
    df_combined = df_combined[df_combined['date'] < dnesny_den].copy()
    
    df_combined['year'] = df_combined['date'].dt.year
    df_combined['month'] = df_combined['date'].dt.month
    df_combined['quarter'] = df_combined['date'].dt.quarter
    
    print(f"-> [DATA] Definitivne data pripravene. Rozsah: {df_combined['date'].min().strftime('%Y-%m-%d')} az {df_combined['date'].max().strftime('%Y-%m-%d')}")
    return df_combined

import pandas as pd
import numpy as np
import datetime

# historical monthly returns from coinglass (2013 - 2020)
COINGLASS_HISTORY_M = {
    2013: {1: 0.4405, 2: 0.6177, 3: 1.7276, 4: 0.5001, 5: -0.0856, 6: -0.2989, 7: 0.0960, 8: 0.3042, 9: -0.0176, 10: 0.6079, 11: 4.4935, 12: -0.3481},
    2014: {1: 0.1003, 2: -0.3103, 3: -0.1725, 4: -0.0160, 5: 0.3946, 6: 0.0220, 7: -0.0969, 8: -0.1753, 9: -0.1901, 10: -0.1295, 11: 0.1282, 12: -0.1511},
    2015: {1: -0.3305, 2: 0.1843, 3: -0.0438, 4: -0.0346, 5: -0.0317, 6: 0.1519, 7: 0.0820, 8: -0.1867, 9: 0.0235, 10: 0.3349, 11: 0.1927, 12: 0.1383},
    2016: {1: -0.1483, 2: 0.2008, 3: -0.0535, 4: 0.0727, 5: 0.1878, 6: 0.2714, 7: -0.0767, 8: -0.0749, 9: 0.0604, 10: 0.1471, 11: 0.0542, 12: 0.3080},
    2017: {1: 0.0004, 2: 0.2307, 3: -0.0905, 4: 0.3271, 5: 0.5271, 6: 0.1045, 7: 0.1792, 8: 0.6532, 9: -0.0744, 10: 0.4781, 11: 0.5348, 12: 0.3889},
    2018: {1: -0.2541, 2: 0.0047, 3: -0.3285, 4: 0.3343, 5: -0.1899, 6: -0.1462, 7: 0.2096, 8: -0.0927, 9: -0.0558, 10: -0.0383, 11: -0.3657, 12: -0.0515},
    2019: {1: -0.0858, 2: 0.1114, 3: 0.0705, 4: 0.3463, 5: 0.5238, 6: 0.2667, 7: -0.0659, 8: -0.0460, 9: -0.1338, 10: 0.1017, 11: -0.1727, 12: -0.0515},
    2020: {1: 0.2995, 2: -0.0860, 3: -0.2492, 4: 0.3426, 5: 0.0951, 6: -0.0318, 7: 0.2403, 8: 0.0283, 9: -0.0751, 10: 0.2770, 11: 0.4295, 12: 0.4692}
}

# historical quarterly returns from coinglass (2013 - 2020)
COINGLASS_HISTORY_Q = {
    2013: {1: 5.3996, 2: -0.0397, 3: -0.4060, 4: 4.7959},
    2014: {1: -0.3742, 2: 0.4043, 3: -0.3974, 4: -0.1670},
    2015: {1: -0.2414, 2: 0.0757, 3: -0.1005, 4: 0.8124},
    2016: {1: -0.0306, 2: 0.6206, 3: -0.0941, 4: 0.5817},
    2017: {1: 0.1189, 2: 1.2386, 3: 0.8041, 4: 2.1507},
    2018: {1: -0.4970, 2: -0.0771, 3: 0.0361, 4: -0.4216},
    2019: {1: 0.0874, 2: 1.5936, 3: -0.2286, 4: -0.1354},
    2020: {1: -0.1083, 2: 0.4233, 3: 0.1797, 4: 1.6802}
}

def generate_coinglass_matrices(df, start_year):
    mesiac_nazvy = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    # timeline preparation from spot data
    df_res = df.sort_values('date').set_index('date')
    current_year = df_res.index.year.max()
    
    # baseline resample for modern period
    df_m = df_res['close'].resample('ME').last().to_frame()
    df_m['ret'] = df_m['close'].pct_change()
    df_m['year'] = df_m.index.year
    df_m['month'] = df_m.index.month
    
    df_q = df_res['close'].resample('QE').last().to_frame()
    df_q['ret'] = df_q['close'].pct_change()
    df_q['year'] = df_q.index.year
    df_q['quarter'] = df_q.index.quarter

    # injection of historical data
    for year, months in COINGLASS_HISTORY_M.items():
        for month, official_ret in months.items():
            mask = (df_m['year'] == year) & (df_m['month'] == month)
            if mask.any():
                df_m.loc[mask, 'ret'] = official_ret
            else:
                # date fallback for missing monthly entries
                fake_date = pd.Timestamp(year=year, month=month, day=28)
                df_m.loc[fake_date] = [np.nan, official_ret, year, month]

    for year, quarters in COINGLASS_HISTORY_Q.items():
        for quarter, official_ret in quarters.items():
            mask = (df_q['year'] == year) & (df_q['quarter'] == quarter)
            if mask.any():
                df_q.loc[mask, 'ret'] = official_ret
            else:
                fake_date = pd.Timestamp(year=year, month=quarter*3, day=28)
                df_q.loc[fake_date] = [np.nan, official_ret, year, quarter]

    monthly_rows = []
    quarterly_rows = []

    # generation of table rows
    for year in range(current_year, start_year - 1, -1):
        row_m = {"year": int(year), "periods_list": []}
        row_q = {"year": int(year), "periods_list": []}
        
        # monthly return calculation
        compounded_yearly_ret = 1.0
        has_data_m = False
        
        for m_idx in range(1, 13):
            m_label = mesiac_nazvy[m_idx - 1]
            sub_m = df_m[(df_m['year'] == year) & (df_m['month'] == m_idx)]
            
            if not sub_m.empty and not pd.isna(sub_m['ret'].iloc[0]):
                m_ret = sub_m['ret'].iloc[0]
                row_m["periods_list"].append({"period_label": m_label, "raw_value": float(round(m_ret, 4)), "display_value": f"{m_ret * 100:+.2f}%"})
                compounded_yearly_ret *= (1 + m_ret)
                has_data_m = True
            else:
                row_m["periods_list"].append({"period_label": m_label, "raw_value": None, "display_value": "N/A"})
        
        # calculation of yearly returns
        if year <= 2020 and has_data_m:
            y_ret = compounded_yearly_ret - 1
            row_m["periods_list"].append({"period_label": "Yearly", "raw_value": float(round(y_ret, 4)), "display_value": f"{y_ret * 100:+.2f}%"})
        else:
            year_days = df_res[df_res.index.year == year]
            if not year_days.empty:
                prev_year_days = df_res[df_res.index.year == (year - 1)]
                y_start = prev_year_days['close'].iloc[-1] if not prev_year_days.empty else year_days['close'].iloc[0]
                y_end = year_days['close'].iloc[-1]
                y_ret = (y_end / y_start) - 1
                row_m["periods_list"].append({"period_label": "Yearly", "raw_value": float(round(y_ret, 4)), "display_value": f"{y_ret * 100:+.2f}%"})
            else:
                row_m["periods_list"].append({"period_label": "Yearly", "raw_value": None, "display_value": "N/A"})
            
        monthly_rows.append(row_m)

        # quarterly return calculation
        for q_idx in range(1, 5):
            q_label = f"Q{q_idx}"
            sub_q = df_q[(df_q['year'] == year) & (df_q['quarter'] == q_idx)]
            
            if not sub_q.empty and not pd.isna(sub_q['ret'].iloc[0]):
                q_ret = sub_q['ret'].iloc[0]
                row_q["periods_list"].append({"period_label": q_label, "raw_value": float(round(q_ret, 4)), "display_value": f"{q_ret * 100:+.2f}%"})
            else:
                row_q["periods_list"].append({"period_label": q_label, "raw_value": None, "display_value": "N/A"})
                
        # quarterly yearly return mapping
        row_q["periods_list"].append({"period_label": "Yearly", "raw_value": row_m["periods_list"][-1]["raw_value"], "display_value": row_m["periods_list"][-1]["display_value"]})
        quarterly_rows.append(row_q)

    # calculation of column statistics
    def calc_stats_for_columns(matrix_rows, labels):
        avg_list = []
        med_list = []
        
        now = pd.Timestamp.now()
        current_quarter_label = f"Q{((now.month - 1) // 3) + 1}"
        current_month_label = mesiac_nazvy[now.month - 1]
        
        for key in labels:
            col_vals = []
            for r in matrix_rows:
                for item in r["periods_list"]:
                    if item["period_label"] == key and item["raw_value"] is not None:
                        # exclusion of ongoing active period returns from historical metrics
                        if r["year"] == current_year and key in ["Yearly", current_quarter_label, current_month_label]:
                            continue
                        col_vals.append(item["raw_value"])
                        
            if len(col_vals) > 0:
                avg_v = np.mean(col_vals)
                med_v = np.median(col_vals)
                avg_list.append({"period_label": key, "raw_value": float(round(avg_v, 4)), "display_value": f"{avg_v * 100:+.2f}%"})
                med_list.append({"period_label": key, "raw_value": float(round(med_v, 4)), "display_value": f"{med_v * 100:+.2f}%"})
            else:
                avg_list.append({"period_label": key, "raw_value": None, "display_value": "N/A"})
                med_list.append({"period_label": key, "raw_value": None, "display_value": "N/A"})
                
        return {"averages": avg_list, "medians": med_list}

    stats_m = calc_stats_for_columns(monthly_rows, mesiac_nazvy + ["Yearly"])
    stats_q = calc_stats_for_columns(quarterly_rows, ["Q1", "Q2", "Q3", "Q4", "Yearly"])

    return {
        "monthly_matrix": {"table_structure": {"columns": ["Year"] + mesiac_nazvy + ["Yearly"], "rows": monthly_rows, "stats": stats_m}},
        "quarterly_matrix": {"table_structure": {"columns": ["Year", "Q1", "Q2", "Q3", "Q4", "Yearly"], "rows": quarterly_rows, "stats": stats_q}}
    }

def run_heatmap_matrix_analysis():
    print("-> [START] Spustam vypocet Heatmaps bez chyb chybajucich dat...")
    
    df_raw = load_and_merge_data()

    aktualna_cena = df_raw['close'].iloc[-1]
    aktualny_datum = df_raw['date'].iloc[-1].strftime('%Y-%m-%d')
    
    heatmap_datasets = generate_coinglass_matrices(df_raw, START_YEAR)

    doc_data = {
        "meta": {
            "title": config.WIDGET_TABLE_HISTORICAL_RETURN_TITLE,
            "subtitle": config.WIDGET_TABLE_HISTORICAL_RETURN_SUBTITLE,
            "current_price": float(aktualna_cena),
            "last_updated_date": aktualny_datum,
            "start_year_filter": int(START_YEAR)
        },
        "heatmap_datasets": heatmap_datasets,
        "ai_content": {
            "summary": f"Najnovsia uzatvorena cena BTC k dnu {aktualny_datum} je ${aktualna_cena:,.2f}.",
            "model_version": "3.8.0_heatmap_floor_date_fixed"
        }
    }
    
    # database export
    conn = db_exporter.get_db_connection()
    try:
        db_exporter.init_database(conn)
        id_widget = "btc_heatmap_returns_matrix" 
        
        db_exporter.save_chart_document(
            conn, 
            id_widget, 
            aktualny_datum, 
            config.WIDGET_CRYPTO_CATEGORY, 
            doc_data,
            has_access=True, 
            is_premium=False
        )
        print("-> [POSTGRES] Heatmap dokument bol uspesne vygenerovany a zapisany.")

    except Exception as e:
        print(f"[EXPORT CRITICAL ERROR] Zlyhal export matic do databazy: {e}")
    finally:
        conn.close()
        print("-> [POSTGRES] Spojenie s databazou uzatvorene.")


if __name__ == "__main__":
    run_heatmap_matrix_analysis()