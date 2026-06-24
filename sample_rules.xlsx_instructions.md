# How to create your Rules Excel file

Create a `.xlsx` file with one sheet and **two columns**: `Rule` and `Columns`.

| Rule | Columns |
|------|---------|
| Revenue = Units * Price | total_revenue, quantity_sold, unit_price |
| Discount <= 0.5 * Revenue | discount_amount, total_revenue |
| order_date <= ship_date | order_date, ship_date |
| tax_amount = Revenue * 0.18 | tax_amount, total_revenue |
| quantity > 0 | quantity |

**The `Columns` column is optional per row.**
- If you fill it in → the agent only validates those specific columns for that rule.
  The LLM is explicitly told to ignore all other columns.
- If you leave it blank → the agent looks at all columns in both tables to figure out the mapping.

Tips:
- Column names in `Columns` should be comma-separated exact column names from either table.
- Use plain English / math formulas in `Rule` — the agent maps terms to column names automatically.
- You can add more columns (e.g. `Description`, `Owner`) — the agent ignores anything it doesn't recognise.
- Save as `.xlsx` (not `.xls`).
