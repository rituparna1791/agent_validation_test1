"""
Databricks App — Streamlit UI for the Validation Agent.
Deploy this as a Databricks App (Apps > Create App > Streamlit).
"""

import os
import tempfile
import time
from io import StringIO

import pandas as pd
import streamlit as st

import config
from validation_agent import ValidationAgent, ValidationReport


# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Data Validation Agent",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 Data Validation Agent")
st.caption("Upload your rules, name your tables — the agent does the rest.")

# ── Sidebar: connection settings ──────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Connection Settings")
    st.markdown("Fill these in once. They are stored only in your session.")

    host = st.text_input(
        "Databricks Host",
        value=config.DATABRICKS_HOST,
        placeholder="adb-1234567890.12.azuredatabricks.net",
        help="Your workspace hostname (no https://).",
    )
    token = st.text_input(
        "Databricks Token",
        value=config.DATABRICKS_TOKEN,
        type="password",
        help="Personal access token (Settings → Developer → Access Tokens).",
    )
    warehouse_id = st.text_input(
        "SQL Warehouse ID",
        value=config.SQL_WAREHOUSE_ID,
        placeholder="abc123def456",
        help="SQL Warehouses → your warehouse → Connection details → HTTP path last segment.",
    )
    llm_model = st.selectbox(
        "LLM Model",
        options=[
            "databricks-meta-llama-3-3-70b-instruct",
            "databricks-dbrx-instruct",
            "databricks-mixtral-8x7b-instruct",
        ],
        index=0,
    )
    st.divider()
    st.markdown("**Excel Rules Format**")
    st.markdown(
        "Two columns in the Excel file:\n\n"
        "| Rule | Columns |\n"
        "|------|---------|\n"
        "| `Revenue = Units * Price` | `total_revenue, quantity_sold, unit_price` |\n"
        "| `order_date <= ship_date` | `order_date, ship_date` |\n"
        "| `quantity > 0` | `quantity` |\n\n"
        "**Columns** is optional per row — leave it blank and the agent "
        "will look at all columns."
    )

# ── Main form ─────────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)
with col1:
    raw_table = st.text_input(
        "Raw / Source Table",
        placeholder="main.default.raw_orders",
        help="Fully qualified name: catalog.schema.table",
    )
with col2:
    new_table = st.text_input(
        "New / Target Table",
        placeholder="main.default.new_orders",
        help="Fully qualified name: catalog.schema.table",
    )

excel_file = st.file_uploader(
    "Upload Rules Excel (.xlsx)",
    type=["xlsx"],
    help="Excel file with one business rule per row.",
)

run_btn = st.button("▶️  Run Validation", type="primary", use_container_width=True)

# ── Validation run ────────────────────────────────────────────────────────────

if run_btn:
    errors: list[str] = []
    if not host:    errors.append("Databricks Host is required.")
    if not token:   errors.append("Databricks Token is required.")
    if not warehouse_id: errors.append("SQL Warehouse ID is required.")
    if not raw_table:    errors.append("Raw table name is required.")
    if not new_table:    errors.append("New table name is required.")
    if not excel_file:   errors.append("Please upload a rules Excel file.")

    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    # Override config values with what the user typed in the sidebar
    config.DATABRICKS_HOST  = host
    config.DATABRICKS_TOKEN = token
    config.SQL_WAREHOUSE_ID = warehouse_id
    config.LLM_MODEL_NAME   = llm_model

    # Save uploaded file to a temp location so openpyxl can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(excel_file.getbuffer())
        tmp_path = tmp.name

    # Chat-style progress log
    st.divider()
    st.subheader("📋 Agent Log")
    log_placeholder = st.empty()
    log_lines: list[str] = []

    def append_log(msg: str):
        log_lines.append(msg)
        log_placeholder.markdown("\n\n".join(log_lines))

    report: ValidationReport | None = None
    try:
        agent = ValidationAgent(
            warehouse_id=warehouse_id,
            host=host,
            token=token,
        )
        report = agent.run(
            excel_path=tmp_path,
            raw_table=raw_table,
            new_table=new_table,
            on_progress=append_log,
        )
    except Exception as exc:
        st.error(f"Agent failed: {exc}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    # ── Report ────────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("📊 Validation Report")

    # Score card
    score_color = "green" if report.quality_score >= 80 else ("orange" if report.quality_score >= 50 else "red")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Quality Score", f"{report.quality_score}%")
    c2.metric("Total Rules",   report.total_rules)
    c3.metric("✅ Passed",     report.passed)
    c4.metric("❌ Failed",     report.failed)
    c5.metric("⚠️ Errors",    report.errors)

    st.caption(
        f"Raw table: **{report.raw_table}** ({report.raw_row_count:,} rows)  |  "
        f"New table: **{report.new_table}** ({report.new_row_count:,} rows)"
    )

    # Per-rule details
    st.subheader("Rule-by-Rule Breakdown")
    for i, r in enumerate(report.rule_results, 1):
        icon  = "✅" if r.status == "PASS" else ("❌" if r.status == "FAIL" else "⚠️")
        label = f"{icon} Rule {i}: `{r.rule_text}`"

        with st.expander(label, expanded=(r.status != "PASS")):
            st.markdown(f"**Status:** {r.status}")

            if r.columns_in_scope:
                st.markdown(f"**Columns in scope:** `{', '.join(r.columns_in_scope)}`")
            else:
                st.markdown("**Columns in scope:** *(all columns — no scope specified)*")

            if r.error_message:
                st.error(r.error_message)

            if r.generated_sql:
                st.code(r.generated_sql, language="sql")

            if r.status == "FAIL":
                st.markdown(f"**Failing rows:** {r.failing_row_count:,}")
                if r.sample_bad_rows:
                    st.markdown("**Sample bad rows:**")
                    st.dataframe(pd.DataFrame(r.sample_bad_rows), use_container_width=True)

    # Download report as CSV
    csv_rows = []
    for r in report.rule_results:
        csv_rows.append({
            "Rule": r.rule_text,
            "Columns in Scope": ", ".join(r.columns_in_scope) if r.columns_in_scope else "all",
            "Status": r.status,
            "Failing Rows": r.failing_row_count,
            "Error": r.error_message,
            "Generated SQL": r.generated_sql,
        })
    csv_buf = StringIO()
    pd.DataFrame(csv_rows).to_csv(csv_buf, index=False)
    st.download_button(
        "⬇️  Download Report CSV",
        data=csv_buf.getvalue(),
        file_name="validation_report.csv",
        mime="text/csv",
    )
