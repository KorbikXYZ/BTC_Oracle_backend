import psycopg2
from psycopg2.extras import Json
import os
import sys
import numpy as np
import config

def get_db_connection():
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_pass = os.getenv("POSTGRES_PASSWORD", "mojeheslo")
    db_name = os.getenv("POSTGRES_DB", "crypto_analytics")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    try:
        return psycopg2.connect(host=config.DB_HOST, port=db_port, database=db_name, user=db_user, password=db_pass, connect_timeout=2)
    except psycopg2.OperationalError:
        docker_host = os.getenv("POSTGRES_CONTAINER_NAME", "postgres")
        print(f"[DB CONNECT] Localhost ({config.DB_HOST}) odmietol spojenie. Prepnam na Docker: '{docker_host}'")
        try:
            return psycopg2.connect(host=docker_host, port=db_port, database=db_name, user=db_user, password=db_pass)
        except Exception as ex:
            print(f"[DB CRITICAL ERROR] Spojenie zlyhalo: {ex}")
            raise ex

def init_database(conn):
    cur = conn.cursor()
    try:
        cur.execute(config.SQL_CREATE_WIDGETS_TABLE)
        cur.execute(config.SQL_CREATE_SERIES_TABLE)
        conn.commit()
    except Exception as e:
        print(f"[DB ERROR] Zlyhala inicializacia tabuliek: {e}")
        conn.rollback()
    finally:
        cur.close()

def save_metric_value(conn, date_str, metric_name, value):
    # upsert of metric value for given day
    if value is None or np.isnan(value): return
    cur = conn.cursor()
    try:
        cur.execute(config.SQL_UPSERT_TIME_SERIES, (date_str, metric_name, float(value)))
        conn.commit()
    except Exception as e:
        print(f"[DB ERROR] Zlyhal zapis metriky {metric_name}: {e}")
        conn.rollback()
    finally:
        cur.close()

def save_chart_document(conn, doc_id, chart_date, category, json_data, has_access=False, is_premium=False):
    cur = conn.cursor()
    try:
        # addition of access flags in tuple for sql query execution
        cur.execute(config.SQL_UPSERT_FLUTTER_WIDGET, (
            doc_id, 
            chart_date, 
            category, 
            Json(json_data),
            bool(has_access),
            bool(is_premium)
        ))
        conn.commit()
        print(f"-> [POSTGRES] Uspesne aktualizovany dokument: '{doc_id}'")
    except Exception as e:
        print(f"[DB ERROR] Zlyhal zapis dokumentu {doc_id}: {e}")
        conn.rollback()
    finally:
        cur.close()


def get_last_recorded_date(conn, metric_name):
    # retrieval of latest saved date for metric
    cur = conn.cursor()
    try:
        # extraction of max date column from time series table
        cur.execute(f"""
            SELECT MAX(date) FROM {config.DB_TABLE_TIME_SERIES} 
            WHERE metric_name = %s;
        """, (metric_name,))
        res = cur.fetchone()
        if res and res[0] is not None:
            return res[0]  # direct return of sql date
        return None
    except Exception as e:
        print(f"[DB ERROR] Nepodarilo sa zistit posledny datum pre {metric_name}: {e}")
        return None
    finally:
        cur.close()