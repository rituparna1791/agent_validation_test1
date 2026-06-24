# Data Validation Agent — Setup Guide

A Streamlit chat-style UI that validates a new Databricks table against business rules written in Excel.

---

## Files

| File | What it does |
|------|-------------|
| `app.py` | Streamlit UI — this is the entry point |
| `validation_agent.py` | Core agent: reads Excel, fetches schemas, generates SQL, runs it |
| `config.py` | Default config values (overridden by env vars or UI) |
| `requirements.txt` | Python dependencies |

---

## Step 1 — Prerequisites in your Databricks workspace

### 1a. Enable a Foundation Model API endpoint
Go to **Serving** → check that one of these endpoints is **Running**:
- `databricks-meta-llama-3-3-70b-instruct`  ← recommended
- `databricks-dbrx-instruct`

If none are enabled: Serving → Create Serving Endpoint → select a Foundation Model → Deploy.

### 1b. Have a running SQL Warehouse
Go to **SQL Warehouses** → note the warehouse name.
Click the warehouse → **Connection details** → copy the last segment of HTTP path.
Example: HTTP path = `/sql/1.0/warehouses/abc123def456` → Warehouse ID = `abc123def456`

### 1c. Create a Personal Access Token
**Settings (top right) → Developer → Access Tokens → Generate new token**
Copy and save it — you won't see it again.

---

## Step 2 — Deploy as a Databricks App

### Option A — via the Databricks UI (easiest)

1. In your workspace, go to **Apps** (left sidebar).
2. Click **Create App**.
3. Choose **Custom** (not a template).
4. Give it a name, e.g. `validation-agent`.
5. Under **Source**, choose **Git repository** and paste this repo's URL.  
   Or choose **Upload files** and upload all 4 files (`app.py`, `validation_agent.py`, `config.py`, `requirements.txt`).
6. Set the **Entry point** to `app.py`.
7. Under **Environment variables**, add:
   ```
   DATABRICKS_HOST    = <your workspace hostname>
   DATABRICKS_TOKEN   = <your PAT>
   SQL_WAREHOUSE_ID   = <your warehouse ID>
   ```
8. Click **Deploy**.
9. Once the app is Running, click the URL — you will see the Streamlit UI.

### Option B — via Databricks CLI

```bash
# Install CLI if you haven't already
pip install databricks-cli

# Authenticate
databricks configure --token

# Deploy
databricks apps deploy validation-agent \
  --source-code-path . \
  --env DATABRICKS_HOST=<host> \
  --env DATABRICKS_TOKEN=<token> \
  --env SQL_WAREHOUSE_ID=<warehouse_id>
```

---

## Step 3 — Use the Agent

1. Open the app URL.
2. In the **sidebar**, confirm the Host, Token, and Warehouse ID are filled in.
3. On the main page:
   - Enter the **Raw table** name (e.g. `main.sales.raw_orders`)
   - Enter the **New table** name (e.g. `main.sales.new_orders`)
   - Upload your **rules Excel file** (see format below)
4. Click **Run Validation**.
5. Watch the live agent log, then see the full report with pass/fail per rule and bad row samples.
6. Download the report as CSV if needed.

---

## Excel Rules Format

Create a `.xlsx` file with a header row `Rule` and one rule per row:

| Rule |
|------|
| Revenue = Units * Price |
| Discount <= 0.5 * Revenue |
| order_date <= ship_date |
| quantity > 0 |

- Use plain math/English — the agent figures out which columns map to your terms.
- No need to use actual column names; the LLM reads both table schemas and maps them.

---

## Environment Variables Reference

| Variable | Required | Example |
|----------|----------|---------|
| `DATABRICKS_HOST` | Yes | `adb-1234567890.12.azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Yes | `dapi...` |
| `SQL_WAREHOUSE_ID` | Yes | `abc123def456` |
| `LLM_MODEL_NAME` | No | `databricks-meta-llama-3-3-70b-instruct` |
| `DEFAULT_CATALOG` | No | `main` |
| `DEFAULT_SCHEMA` | No | `default` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Connection refused` | Check that `DATABRICKS_HOST` has no `https://` prefix |
| `403 Unauthorized` | Token expired or wrong — generate a new one |
| `Warehouse not found` | Confirm the warehouse ID from SQL Warehouses → Connection details |
| `Model endpoint not found` | Enable the Foundation Model endpoint in Serving |
| `DESCRIBE TABLE failed` | Make sure the token has SELECT permission on both tables |
| SQL returns unexpected results | Check the Generated SQL in the rule expander and adjust the rule wording |

---

## How it works (quick summary)

```
You upload Excel rules + enter table names
        ↓
Agent calls DESCRIBE TABLE on both tables (Unity Catalog)
        ↓
For each rule: LLM (Llama/DBRX) maps terms to columns and writes SQL
        ↓
Databricks SQL Warehouse runs the SQL — returns failing rows
        ↓
Streamlit UI shows pass/fail + sample bad rows + quality score
```
