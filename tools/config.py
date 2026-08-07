import os
import datetime
from enum import Enum
from dotenv import load_dotenv

# postgresql configuration setup
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = int(os.getenv("POSTGRES_PORT"))
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASS = os.getenv("POSTGRES_PASSWORD")

# resolution of absolute path for config directory
config_dir = os.path.dirname(os.path.abspath(__file__))

# definition of project root path
#project_root = os.path.dirname(config_dir)
project_root = os.getcwd()

# loading of environment variables from env file
dotenv_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path=dotenv_path)

# binance and parquet file path configurations
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL")
if not BINANCE_BASE_URL:
    raise ValueError(f"Chyba: V .env subore {dotenv_path} nebola najdena premenna BINANCE_BASE_URL!")

PARQUET_OUTPUT_PATH = os.getenv("PARQUET_OUTPUT_PATH")
if not PARQUET_OUTPUT_PATH:
    raise ValueError("Chyba: V .env subore nebola najdena premenna PARQUET_OUTPUT_PATH!")

DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "--day")

BINANCE_OPEN_INTEREST_URL=os.getenv("BINANCE_OPEN_INTEREST_URL")
BINANCE_DEPTH_URL=os.getenv("BINANCE_DEPTH_URL")
FILENAME_OI_OUTPUT_PATH = "BTC_OI.parquet"
HISTOGRAM_LIKVIDATION_MAP= "open_interest_histogram"

# coinmetrics on-chain data configurations
GITHUBUSERCONTENT_URL = os.getenv("GITHUBUSERCONTENT_URL")
if not GITHUBUSERCONTENT_URL:
    raise ValueError(f"Chyba: V .env subore {dotenv_path} nebola najdena premenna GITHUBUSERCONTENT_URL!")

START_YEAR = 2013

FILENAME_ONCHAIN = "BTC_onchain.parquet"
ONCHAIN_REQUEST_TIMEOUT_SECONDS = 30

# fear and greed index configurations
ALTTERNATIVE_URL = os.getenv("ALTTERNATIVE_URL")
if not ALTTERNATIVE_URL:
    raise ValueError(f"Chyba: V .env subore {dotenv_path} nebola najdena premenna ALTTERNATIVE_URL!")

FILENAME_FNG = "BTC_fear_and_greed_index.parquet"
FNG_REQUEST_TIMEOUT_SECONDS = 20

# market cap data configurations
BLOCKCHAININFO_URL_MARKET_CAP = os.getenv("BLOCKCHAININFO_URL_MARKET_CAP")
if not BLOCKCHAININFO_URL_MARKET_CAP:
    raise ValueError(f"Chyba: V .env subore {dotenv_path} nebola najdena premenna ALTTERNATIVE_URL!")

# dune analytics api configurations
DUNE_QUERY_ID = "7873117"  # Vaše ID
DUNE_API_KEY = os.getenv("DUNE_API_KEY")
DUNE_API_BASE_URL = os.getenv("DUNE_API_BASE_URL")
DUNE_EXECUTE= "/execute"
DUNE_STATUS= "/status"
DUNE_RESULT= "/results/csv"
FILENAME_DUNE_BTC = "DUNE_on_chain.parquet"
DUNE_REQUEST_TIMEOUT_SECONDS = 30
START_FETCH_DATE="2026-05-01"
USE_DUNE_DATA=False


FILENAME_TXT_MANUAL = "on_chain_data_manual.txt"

# internal runtime configuration default values
DEFAULT_SYMBOL = "BTCUSDT"
API_MAX_LIMIT = 1000

# default fallback start date definition
DEFAULT_START_DATE = datetime.datetime(2017, 6, 1, tzinfo=datetime.timezone.utc)

# target file names for data output
FILENAME_MINUTE = "BTC_1m.parquet"
FILENAME_DAY = "BTC_1d.parquet"

# network request timeout and rate limiting parameters
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
REQUEST_TIMEOUT_SECONDS = 15
SUCCESS_SLEEP_SECONDS = 0.02
ERROR_SLEEP_SECONDS = 5

# console output progress interval setting
PROGRESS_PRINT_INTERVAL_ROWS = 50000

# retrieval of root directory path
def get_project_root():
    return project_root

# output directory paths for artifacts
OUTPUT_GRAPHS_DIR = "output/graphs"
OUTPUT_SUMMARY_DIR = "output/summary"


# power-law regression and bucket analysis settings
GENESIS_DATE_STR = '2009-01-03'
BUCKET_WIDTH = 0.10

POWER_LAW_MULTI_HORIZONTS_FILENAME = "bitcoin_multi_horizon_power_law"
NUPL = "NUPL"

# definition of forward return time horizons in days
HORIZONS = {
    '1M': 30,
    '2M': 60,
    '3M': 90,
    '6M': 180,
    '9M': 270,
    '365D': 365
}

# horizon order sequence for exported summary tables
HORIZON_COLUMNS_ORDER = ['1M', '2M', '3M', '6M', '9M', '365D']

# percentile breakdown targets for returns analysis
PERCENTILES = [10, 25, 50, 75, 90]

# graph plot display parameters
GRAPH_SIZE_POWER_LAW = (13, 8)
GRAPH_YLIM_MIN = -1.5
GRAPH_YLIM_MAX = 3.5
ROLLING_MEDIAN_WINDOW = 100

TREND_COLORS = {
    '1M': '#ff4560',    # red
    '2M': '#ff9f43',    # orange
    '3M': '#f1c40f',    # yellow
    '6M': '#00b894',    # turquoise
    '9M': '#0984e3',    # blue
    '365D': '#00ff66'   # light green
}

# power-law oscillator parameters
POWER_LAW_OSCILLATOR_FILENAME = "bitcoin_power_law_oscillator"
GRAPH_SIZE_OSCILLATOR = (12, 10)

# bitcoin halving event dates
HALVING_DATES = ['2020-05-11', '2024-04-19']

# valuation z-score threshold definitions
Z_SCORE_LIMIT_STRONG_OVERVALUED = 1.5
Z_SCORE_LIMIT_OVERVALUED_HIGH = 1.5
Z_SCORE_LIMIT_OVERVALUED_LOW = 0.5
Z_SCORE_LIMIT_NEUTRAL_HIGH = 0.5
Z_SCORE_LIMIT_NEUTRAL_LOW = -0.5
Z_SCORE_LIMIT_UNDERVALUED_HIGH = -0.5
Z_SCORE_LIMIT_UNDERVALUED_LOW = -1.5

# status text labels and color hex mappings
STATUS_STRONG_OVERVALUED = "SILNE NADHODNOTENE (VRCHOL)"
STATUS_OVERVALUED = "NADHODNOTENE (DRAHE)"
STATUS_NEUTRAL = "NEUTRALNE PASMO (FEROVA CENA)"
STATUS_UNDERVALUED = "PODHODNOTENE (LACNE)"
STATUS_STRONG_UNDERVALUED = "SILNE PODHODNOTENE (DNO)"

COLOR_STRONG_OVERVALUED = "#c0392b"  # red
COLOR_OVERVALUED = "#d35400"         # orange
COLOR_NEUTRAL = "#f1c40f"            # yellow
COLOR_UNDERVALUED = "#2ecc71"        # green
COLOR_STRONG_UNDERVALUED = "#1abc9c" # turquoise


# on-chain mvrv heatmap report settings
POWER_LAW_ONCHAIN_FILENAME="bitcoin_onchain_mvrv_heatmap"

CYKLUS_DNI = int(os.getenv("CYKLUS_DNI", 1460))

# dynamic file name resolution with fallback
POWER_LAW_ONCHAIN_FILENAME = os.getenv("POWER_LAW_ONCHAIN_FILENAME", "bitcoin_onchain_mvrv_heatmap")

# calculation bounds and threshold limits
EXPANDING_MIN_PERIODS = 30
ROLLING_MIN_PERIODS = 30
MVRV_Z_SCORE_LIMIT_HIGH = 2.0
MVRV_Z_SCORE_LIMIT_MID = 0.5
MVRV_Z_SCORE_LIMIT_LOW = -0.5

# on-chain market status labels
STATUS_ONCHAIN_OVERBOUGHT = "VYSOKA KLADNA ODCHYLKA (OVERBOUGHT)"
STATUS_ONCHAIN_MID_HIGH = "STREDNA KLADNA ODCHYLKA"
STATUS_ONCHAIN_NEUTRAL = "NEUTRALNE PASMO (FEROVA HODNOTA)"
STATUS_ONCHAIN_OVERSOLD = "ZAPORNA ODCHYLKA (OVERSOLD)"

# output chart dimension sizing
GRAPH_SIZE_ONCHAIN_REPORT = (12, 12)


# database table identifiers
DB_TABLE_FLUTTER_WIDGETS = "daily_charts"
DB_TABLE_TIME_SERIES = "btc_metrics_series" # unified metrics table


# chart type enumeration definitions for flutter UI renderer
class ChartType(str, Enum):
    SINGLE_AXIS = "SINGLE_AXIS"
    MULTI_AXIS = "MULTI_AXIS"
    OSCILLATOR = "OSCILLATOR"
    SINGLE_AXIS_LOG = "SINGLE_AXIS_LOG"
    MULTI_AXIS_LOG = "MULTI_AXIS_LOG"
    POWER_LAW_RETURNS = "POWER_LAW_RETURNS"

# timeline snapshot length filter for widget records
FLUTTER_CHART_SNAPSHOT_DAYS = None

# widget document key identifiers
ID_WIDGET_PRICE_HEATMAP = "current_btc_price_fng_heatmap"
ID_WIDGET_ROLLING_Z = f"current_btc_rolling_z_score"
ID_WIDGET_GLOBAL_MVRV = "current_btc_global_onchain_mvrv"

# database schema creation query strings
SQL_CREATE_WIDGETS_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {DB_TABLE_FLUTTER_WIDGETS} (
        id VARCHAR(50) PRIMARY KEY,
        chart_date DATE NOT NULL,
        category VARCHAR(30) NOT NULL,
        doc JSONB NOT NULL,
        has_access BOOLEAN DEFAULT FALSE NOT NULL,  -- access level indicator
        is_premium BOOLEAN DEFAULT FALSE NOT NULL   -- tier identifier flag
    );
"""

SQL_CREATE_SERIES_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {DB_TABLE_TIME_SERIES} (
        date DATE NOT NULL,
        metric_name VARCHAR(50) NOT NULL,
        value NUMERIC(16,4) NOT NULL,
        PRIMARY KEY (date, metric_name)
    );
    CREATE INDEX IF NOT EXISTS idx_metrics_name ON {DB_TABLE_TIME_SERIES}(metric_name);
"""

# database record insertion and update query statements
SQL_UPSERT_TIME_SERIES = f"""
    INSERT INTO {DB_TABLE_TIME_SERIES} (date, metric_name, value)
    VALUES (%s, %s, %s)
    ON CONFLICT (date, metric_name) DO UPDATE SET
        value = EXCLUDED.value;
"""

SQL_UPSERT_FLUTTER_WIDGET = f"""
    INSERT INTO {DB_TABLE_FLUTTER_WIDGETS} (id, chart_date, category, doc, has_access, is_premium)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET 
        chart_date = EXCLUDED.chart_date,
        category = EXCLUDED.category,
        doc = EXCLUDED.doc,
        has_access = EXCLUDED.has_access,
        is_premium = EXCLUDED.is_premium;
"""


# flutter chart visual theme settings
WIDGET_CRYPTO_CATEGORY = "crypto"

# color palette definition strings
COLOR_FLUTTER_BTC = "#FF9900"
COLOR_FLUTTER_FNG_MASK = "#2ecc71"
COLOR_FLUTTER_ROLLING_Z = "#e1b12c"
COLOR_FLUTTER_GLOBAL_MVRV = "#3498db"
COLOR_FLUTTER_OSCILLATOR_LINE = "#e1b12c"

# analytics pipeline version strings
MODEL_VERSION_FNG_HEATMAP = "pipeline-fng-heatmap-v1"
MODEL_VERSION_ROLLING_Z = f"pipeline-rolling-{CYKLUS_DNI}d-v1"
MODEL_VERSION_GLOBAL_MVRV = "pipeline-expanding-macro-v1"

# UI title and description strings
WIDGET_PRICE_HEATMAP_TITLE = "Bitcoin Price & Sentiment Heatmap"
WIDGET_PRICE_HEATMAP_SUBTITLE = "Bitcoin spot price color-coded by the Fear & Greed Index"

WIDGET_ROLLING_Z_TITLE = f"Rolling Z-Score"
WIDGET_ROLLING_Z_SUBTITLE = "Local deviation of the spot price from the average"

WIDGET_GLOBAL_MVRV_TITLE = "Global On-Chain MVRV Z-Score"
WIDGET_GLOBAL_MVRV_SUBTITLE = "Deviation of market cap from realized cap since 2009, focused from 2017"


WIDGET_GLOBAL_MVRV_TITLE_FULL = "Global On-Chain MVRV Z-Score Full"
WIDGET_GLOBAL_MVRV_SUBTITLE_FULL = "Deviation of market cap from realized cap since 2009"


# multi-horizon widget configuration constants
ID_WIDGET_MULTI_HORIZONS = "current_btc_power_law_multi_horizons"
WIDGET_MULTI_TITLE = "Bitcoin Multi-Horizon Forward Returns"
WIDGET_MULTI_SUBTITLE = "Historical return probability for the current deviation basket"
MODEL_VERSION_POWER_LAW_MULTI = "pipeline-power-law-multi-v1"

# power law oscillator widget constants

MODEL_VERSION_POWER_LAW_OSCILLATOR = "pipeline-power-law-oscillator-v2"


ID_WIDGET_PL_PRICE_TREND = "current_btc_power_law_price_trend"
ID_WIDGET_PL_DEVIATION_Z = "current_btc_power_law_deviation_oscillator"

WIDGET_PL_PRICE_TITLE = "Bitcoin Power Law Trend & Bands"
WIDGET_PL_PRICE_SUBTITLE = "Bitcoin spot price, modeled fair value, and +-2σ sigma bands"

WIDGET_PL_DEV_TITLE = "Bitcoin Power Law Deviation Oscilator"
WIDGET_PL_DEV_SUBTITLE = "Z-Score deviation of the spot price from the long-term regression trend"

WIDGET_TABLE_HISTORICAL_RETURN_TITLE = "Bitcoin Returns Heatmap"
WIDGET_TABLE_HISTORICAL_RETURN_SUBTITLE = "Historical calendar returns"

# production mode status flag check
FASTAPI_IS_PRODUCTION = os.getenv("IS_PRODUCTION", "False") == "True"

NUPL_START_DATE = "2017-06-01"          #"2015-01-01"
#NUPL_END_DATE = "2016-12-31"