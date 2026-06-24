"""
Core validation agent — no LangChain dependency, just direct calls to:
  • Databricks SQL Connector  (schema reads + query execution)
  • Databricks Foundation Model API via openai SDK  (SQL generation)
  • openpyxl  (Excel rule parsing)
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable

import openpyxl
from databricks import sql as dbsql
from openai import OpenAI

import config


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    rule_text: str
    columns_in_scope: list[str]   # columns the user explicitly scoped this rule to
    generated_sql: str
    status: str                   # "PASS" | "FAIL" | "ERROR"
    failing_row_count: int = 0
    sample_bad_rows: list[dict] = field(default_factory=list)
    error_message: str = ""


@dataclass
class ValidationReport:
    raw_table: str
    new_table: str
    total_rules: int
    passed: int
    failed: int
    errors: int
    quality_score: float          # 0–100
    rule_results: list[RuleResult] = field(default_factory=list)
    raw_row_count: int = 0
    new_row_count: int = 0


# ── Agent ─────────────────────────────────────────────────────────────────────

class ValidationAgent:
    """
    Usage:
        agent = ValidationAgent(
            warehouse_id="abc123",
            host="adb-xxx.azuredatabricks.net",
            token="dapiXXX",
        )
        report = agent.run(
            excel_path="/Volumes/main/default/uploads/rules.xlsx",
            raw_table="main.default.raw_orders",
            new_table="main.default.new_orders",
            on_progress=lambda msg: print(msg),
        )
    """

    def __init__(
        self,
        warehouse_id: str = config.SQL_WAREHOUSE_ID,
        host: str = config.DATABRICKS_HOST,
        token: str = config.DATABRICKS_TOKEN,
    ):
        self.warehouse_id = warehouse_id
        self.host = host.rstrip("/")
        self.token = token

        # OpenAI-compatible client pointing at Databricks Foundation Model API
        self._llm = OpenAI(
            api_key=token,
            base_url=f"https://{self.host}/serving-endpoints",
        )

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        excel_path: str,
        raw_table: str,
        new_table: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> ValidationReport:
        log = on_progress or (lambda m: None)

        log("📂 Reading validation rules from Excel…")
        rules = self._parse_excel(excel_path)   # list of (rule_text, [col, col, ...])
        log(f"   Found {len(rules)} rule(s)")

        log(f"🔍 Fetching schema for raw table `{raw_table}`…")
        raw_schema = self._get_schema(raw_table)
        log(f"   {len(raw_schema['columns'])} columns, {raw_schema['row_count']:,} rows")

        log(f"🔍 Fetching schema for new table `{new_table}`…")
        new_schema = self._get_schema(new_table)
        log(f"   {len(new_schema['columns'])} columns, {new_schema['row_count']:,} rows")

        results: list[RuleResult] = []
        for i, (rule_text, scoped_cols) in enumerate(rules, 1):
            scope_hint = f"  (columns in scope: {', '.join(scoped_cols)})" if scoped_cols else ""
            log(f"\n📐 Rule {i}/{len(rules)}: `{rule_text}`{scope_hint}")
            result = self._validate_rule(
                rule_text, scoped_cols,
                raw_table, raw_schema,
                new_table, new_schema,
                log,
            )
            results.append(result)
            icon = "✅" if result.status == "PASS" else ("❌" if result.status == "FAIL" else "⚠️")
            log(f"   {icon} {result.status}"
                + (f" — {result.failing_row_count:,} failing rows" if result.status == "FAIL" else ""))

        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        errors = sum(1 for r in results if r.status == "ERROR")
        score  = round(100 * passed / len(results), 1) if results else 0.0

        log(f"\n🏁 Done — Quality score: {score}%  ({passed} passed, {failed} failed, {errors} errors)")

        return ValidationReport(
            raw_table=raw_table,
            new_table=new_table,
            total_rules=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            quality_score=score,
            rule_results=results,
            raw_row_count=raw_schema["row_count"],
            new_row_count=new_schema["row_count"],
        )

    # ── Excel parser ──────────────────────────────────────────────────────────

    def _parse_excel(self, path: str) -> list[tuple[str, list[str]]]:
        """
        Returns a list of (rule_text, scoped_columns) tuples.

        Expected Excel columns:
          - Rule / Formula / Validation / Check  — the rule expression (required)
          - Columns / Column / Scope / Fields    — comma-separated column names to scope
                                                   the validation to (optional)

        If the Columns column is absent or blank for a row, scoped_columns = [] meaning
        the LLM uses ALL columns from both schemas to figure out the mapping.
        """
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        header = [str(c).strip().lower() if c else "" for c in rows[0]]

        # Locate rule column
        rule_col = None
        for kw in ("rule", "formula", "validation", "check"):
            if kw in header:
                rule_col = header.index(kw)
                break
        if rule_col is None:
            rule_col = 0  # fallback to column A

        # Locate optional columns-scope column
        col_scope_col = None
        for kw in ("columns", "column", "scope", "fields"):
            if kw in header:
                col_scope_col = header.index(kw)
                break

        results: list[tuple[str, list[str]]] = []
        for row in rows[1:]:
            rule_val = row[rule_col] if rule_col < len(row) else None
            if not rule_val or not str(rule_val).strip():
                continue

            rule_text = str(rule_val).strip()

            scoped_cols: list[str] = []
            if col_scope_col is not None and col_scope_col < len(row):
                scope_val = row[col_scope_col]
                if scope_val and str(scope_val).strip():
                    scoped_cols = [c.strip() for c in str(scope_val).split(",") if c.strip()]

            results.append((rule_text, scoped_cols))

        return results

    # ── Schema reader ─────────────────────────────────────────────────────────

    def _get_schema(self, table_name: str) -> dict:
        """Returns {columns: [{name, type}], sample_rows: [...], row_count: int}"""
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Column info
                cur.execute(f"DESCRIBE TABLE {table_name}")
                raw_cols = cur.fetchall()
                columns = [
                    {"name": r[0], "type": r[1]}
                    for r in raw_cols
                    if r[0] and not r[0].startswith("#")
                ]

                # Sample rows
                cur.execute(f"SELECT * FROM {table_name} LIMIT {config.SCHEMA_SAMPLE_ROWS}")
                col_names = [d[0] for d in cur.description]
                sample_rows = [dict(zip(col_names, row)) for row in cur.fetchall()]

                # Row count
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cur.fetchone()[0]

        return {"columns": columns, "sample_rows": sample_rows, "row_count": row_count}

    # ── Rule validator ────────────────────────────────────────────────────────

    def _validate_rule(
        self,
        rule: str,
        scoped_cols: list[str],
        raw_table: str,
        raw_schema: dict,
        new_table: str,
        new_schema: dict,
        log: Callable[[str], None],
    ) -> RuleResult:
        # Step 1: ask LLM to generate SQL
        log("   🤖 Generating SQL…")
        try:
            sql = self._generate_sql(rule, scoped_cols, raw_table, raw_schema, new_table, new_schema)
            log(f"   SQL preview: {sql[:120].replace(chr(10), ' ')}…")
        except Exception as e:
            return RuleResult(rule_text=rule, columns_in_scope=scoped_cols,
                              generated_sql="", status="ERROR",
                              error_message=f"LLM error: {e}")

        # Step 2: run the SQL on Databricks
        log("   ▶️  Running SQL on Databricks…")
        try:
            bad_rows = self._run_sql(sql)
        except Exception as e:
            return RuleResult(rule_text=rule, columns_in_scope=scoped_cols,
                              generated_sql=sql, status="ERROR",
                              error_message=f"SQL execution error: {e}")

        if bad_rows is None:
            bad_rows = []

        sample = bad_rows[:config.MAX_SAMPLE_ROWS]
        return RuleResult(
            rule_text=rule,
            columns_in_scope=scoped_cols,
            generated_sql=sql,
            status="PASS" if len(bad_rows) == 0 else "FAIL",
            failing_row_count=len(bad_rows),
            sample_bad_rows=sample,
        )

    # ── LLM SQL generation ────────────────────────────────────────────────────

    def _generate_sql(
        self,
        rule: str,
        scoped_cols: list[str],
        raw_table: str,
        raw_schema: dict,
        new_table: str,
        new_schema: dict,
    ) -> str:
        # When the user scoped this rule to specific columns, filter schemas down to only
        # those columns (plus keep all columns for the join-key detection hint).
        # This prevents the LLM from accidentally touching unrelated columns.
        def filter_schema(schema: dict) -> dict:
            if not scoped_cols:
                return schema
            scoped_lower = {c.lower() for c in scoped_cols}
            filtered_cols = [
                c for c in schema["columns"]
                if c["name"].lower() in scoped_lower
            ]
            # Keep at least the full column list as a secondary reference so the LLM
            # can still identify the join key even if it isn't in scoped_cols.
            return {
                "columns": filtered_cols,
                "all_columns_for_join_detection": schema["columns"],
                "sample_rows": [
                    {k: v for k, v in row.items() if k.lower() in scoped_lower}
                    for row in schema["sample_rows"]
                ],
                "row_count": schema["row_count"],
            }

        rs = filter_schema(raw_schema)
        ns = filter_schema(new_schema)

        scope_instruction = (
            f"IMPORTANT: Only validate these columns: {', '.join(scoped_cols)}. "
            "Do NOT reference any other columns in the WHERE clause or computed expressions. "
            "You may use other columns ONLY for the JOIN key.\n"
            if scoped_cols else ""
        )

        system = textwrap.dedent("""
            You are a data validation SQL expert for Databricks (Delta Lake / Spark SQL).
            Given a business rule formula, two table schemas, and sample rows,
            write a single SQL SELECT query that returns ONLY the rows that VIOLATE the rule.
            - If the query returns zero rows → rule passes.
            - If the query returns rows → those rows are failing.
            Rules:
            1. Use Spark SQL syntax.
            2. Always alias the tables: raw_table as R, new_table as N.
            3. For numeric comparisons use ABS(a - b) > {tol} instead of a != b.
            4. Join on the most sensible key columns (primary-key-looking columns).
            5. Return ONLY the SQL query — no explanation, no markdown fences, no comments.
        """.format(tol=config.NUMERIC_TOLERANCE)).strip()

        user = textwrap.dedent(f"""
            {scope_instruction}Rule: {rule}

            RAW TABLE: {raw_table}
            Columns in scope: {json.dumps(rs['columns'], indent=2)}
            All columns (for join key detection only): {json.dumps(rs.get('all_columns_for_join_detection', rs['columns']), indent=2)}
            Sample rows: {json.dumps(rs['sample_rows'][:3], indent=2, default=str)}

            NEW TABLE: {new_table}
            Columns in scope: {json.dumps(ns['columns'], indent=2)}
            All columns (for join key detection only): {json.dumps(ns.get('all_columns_for_join_detection', ns['columns']), indent=2)}
            Sample rows: {json.dumps(ns['sample_rows'][:3], indent=2, default=str)}

            Write the SQL query that returns rows violating this rule.
        """).strip()

        response = self._llm.chat.completions.create(
            model=config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        )

        sql = response.choices[0].message.content.strip()
        # Strip accidental markdown fences
        sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql)
        sql = re.sub(r"\n?```$", "", sql)
        return sql.strip()

    # ── SQL runner ────────────────────────────────────────────────────────────

    def _run_sql(self, sql: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                col_names = [d[0] for d in cur.description]
                rows = cur.fetchall()
        return [dict(zip(col_names, row)) for row in rows]

    # ── DB connection helper ──────────────────────────────────────────────────

    def _connect(self):
        return dbsql.connect(
            server_hostname=self.host,
            http_path=f"/sql/1.0/warehouses/{self.warehouse_id}",
            access_token=self.token,
        )
