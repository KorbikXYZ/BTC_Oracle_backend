
# standard library imports for system and file management
import os
import sys

# fastAPI framework imports for api routing and exception handling
from fastapi import FastAPI, HTTPException
# cors middleware import for cross-origin access control
from fastapi.middleware.cors import CORSMiddleware

# database driver import for postgresql connection
import psycopg2
# database helper import for dict formatted query results
from psycopg2.extras import RealDictCursor

# system path resolution for internal module imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
tools_dir = os.path.join(project_root, "tools")
sys.path.insert(0, tools_dir)

# custom configuration import from tools directory
import config

# fastapi application setup
app = FastAPI(
    title="Bitcoin Power-Law & On-Chain API",
    description="Produkcne API rozhranie pre distribuciu dat do Flutter aplikacie",
    version="1.0.0",
    docs_url=None if config.FASTAPI_IS_PRODUCTION else "/docs",
    redoc_url=None if config.FASTAPI_IS_PRODUCTION else "/redoc",
    openapi_url=None if config.FASTAPI_IS_PRODUCTION else "/openapi.json"
)

# cors headers setup for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# helper function for postgres database connection establishment
def get_db_connection():
    """Vytvori pripojenie do DB (Localhost s fallbackom na Docker meno)."""
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_pass = os.getenv("POSTGRES_PASSWORD", "mojeheslo")
    db_name = os.getenv("POSTGRES_DB", "crypto_analytics")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    try:
        # primary connection attempt using localhost host setting
        return psycopg2.connect(
            host=config.DB_HOST, port=db_port, database=db_name, 
            user=db_user, password=db_pass, connect_timeout=2
        )
    except psycopg2.OperationalError:
        # fallback connection attempt using internal docker host name
        docker_host = os.getenv("POSTGRES_CONTAINER_NAME", "postgres")
        try:
            return psycopg2.connect(
                host=docker_host, port=db_port, database=db_name, 
                user=db_user, password=db_pass
            )
        except Exception:
            raise RuntimeError("Kriticka chyba: Nepodarilo sa spojit s PostgreSQL databazou.")

# root endpoint returning 404 to hide route presence
@app.get("/")
def read_root():
    raise HTTPException(status_code=404, detail="Not Found")

# status endpoint returning list of widgets and timestamps
@app.get("/api/v1/widget/status")
def get_widgets_status():
    """
    Vrati zoznam vsetkych predpripravenych Flutter widgetov z databazy s Unix timestamp.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # selection of widget metadata rows from database
        query = f"""
            SELECT id, chart_date, category, has_access, is_premium 
            FROM {config.DB_TABLE_FLUTTER_WIDGETS} 
            ORDER BY chart_date DESC, id ASC;
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        # conversion of database records into json payload array
        widgets_status = []
        for row in rows:
            # conversion of date object to unix timestamp in seconds
            chart_timestamp = int(row["chart_date"].strftime("%s")) if row["chart_date"] else None
            
            widgets_status.append({
                "id": row["id"],
                "chart_date": chart_timestamp,
                "category": row["category"],
                "has_access": bool(row["has_access"]),
                "is_premium": bool(row["is_premium"])
            })
            
        return {
            "status": "success",
            "total_widgets": len(widgets_status),
            "widgets": widgets_status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Serverova chybe pri nacitavani statusu widgetov: {e}")
    finally:
        cur.close()
        conn.close()


# widget document endpoint returning pre-formatted json chart data
@app.get("/api/v1/widget/{widget_id}")
def get_flutter_widget(widget_id: str):
    """
    Vrati predpripraveny JSONB dokument pre Flutter UI widget.
    Tento endpoint pouzijes pre svoje grafy:
    - current_btc_global_onchain_mvrv
    - current_btc_power_law_deviation_oscillator
    - current_btc_power_law_multi_horizons
    - current_btc_power_law_price_trend
    - current_btc_price_fng_heatmap
    - current_btc_rolling_z_score_1460d
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # extraction of document column for given widget id
        query = f"SELECT doc FROM {config.DB_TABLE_FLUTTER_WIDGETS} WHERE id = %s;"
        cur.execute(query, (widget_id,))
        result = cur.fetchone()
        
        # verification of requested record existence
        if not result:
            raise HTTPException(status_code=404, detail=f"Widget '{widget_id}' sa nenasiel.")
            
        # output of raw database json structure
        return result["doc"]
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Serverova chyba pri citani DB: {e}")
    finally:
        # cleanup of cursor and connection resources
        cur.close()
        conn.close()

# metric series endpoint returning full historical data points
@app.get("/api/v1/series/{metric_name}")
def get_metric_time_series(metric_name: str):
    """
    Vrati kompletny historicky rad dat od roku 2017 pre danu metriku.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # selection of time ordered values for specified metric
        query = f"""
            SELECT date, value 
            FROM {config.DB_TABLE_TIME_SERIES} 
            WHERE metric_name = %s 
            ORDER BY date ASC;
        """
        cur.execute(query, (metric_name,))
        rows = cur.fetchall()
        
        # verification of returned time series data presence
        if not rows:
            raise HTTPException(status_code=404, detail=f"Metrika '{metric_name}' nema ziadne zaznamy alebo neexistuje.")
            
        # declaration of arrays for timestamp and value extraction
        timestamps = []
        values = []
        
        # iteration over database rows for payload preparation
        for row in rows:
            # conversion of date field to unix timestamp integer
            ts = int(row["date"].strftime("%s")) if hasattr(row["date"], "strftime") else int(row["date"])
            timestamps.append(ts)
            # type conversion of value field to float
            values.append(float(row["value"]))
            
        # assembly of final metric series dictionary response
        return {
            "metric_name": metric_name,
            "total_points": len(timestamps),
            "timestamps": timestamps,
            "values": values
        }
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Serverova chyba pri citani casoveho radu: {e}")
    finally:
        # cleanup of cursor and connection resources
        cur.close()
        conn.close()