import os

# ── Databricks connection ────────────────────────────────────────────────────
DATABRICKS_HOST  = os.environ.get("DATABRICKS_HOST", "")   # e.g. "adb-1234567890.12.azuredatabricks.net"
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")  # personal access token or service principal token

# ── SQL Warehouse ────────────────────────────────────────────────────────────
SQL_WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "")   # e.g. "abc123def456"

# ── Unity Catalog defaults (user can override from the UI) ──────────────────
DEFAULT_CATALOG = os.environ.get("DEFAULT_CATALOG", "main")
DEFAULT_SCHEMA  = os.environ.get("DEFAULT_SCHEMA",  "default")

# ── LLM (Databricks Foundation Model API — OpenAI-compatible) ───────────────
# Change the model name to whichever endpoint is enabled in your workspace:
#   "databricks-meta-llama-3-3-70b-instruct"
#   "databricks-dbrx-instruct"
#   "databricks-mixtral-8x7b-instruct"
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "databricks-meta-llama-3-3-70b-instruct")
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.0   # deterministic SQL generation

# ── Validation thresholds ────────────────────────────────────────────────────
NUMERIC_TOLERANCE   = 0.01   # allowed absolute difference for numeric comparisons
MAX_SAMPLE_ROWS     = 10     # bad rows shown per rule in the report
SCHEMA_SAMPLE_ROWS  = 5      # rows fetched to help the LLM understand the data
