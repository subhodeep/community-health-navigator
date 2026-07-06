"""AnalyticsAgent — NL->SQL over BigQuery with guarded execution (Flow B)."""
from google.adk.agents import Agent

from shared.config import load_config
from tools.bigquery import get_schema, run_bigquery
from tools.charts import render_chart_spec

_INSTRUCTION = """You turn analytical questions into BigQuery Standard SQL over the
community_health dataset and explain the results.

Workflow:
1. Call get_schema to see the exact tables and columns.
2. Write ONE SELECT statement (unqualified table names; the dataset is preset).
   - Read-only; only the documented tables; results are capped at 200 rows, so
     aggregate (GROUP BY) rather than selecting raw rows.
   - Arrays: use 'value' IN UNNEST(column) for services/accepts filters.
3. Call run_bigquery. If it returns {"error": ...}, fix the SQL and retry — at most
   2 retries. After that, apologize and show the closest schema hints instead.
4. When results suit a chart (trends, comparisons, distributions), call
   render_chart_spec (pick line for time series, bar for comparisons). The chart and
   the executed SQL are attached to your reply automatically.
5. Finish with a 2-4 sentence narrative: the direct answer first, then key numbers.
   Mention that the SQL is viewable in the chart panel.

Facility lookups for citizens (e.g. "flu shots near ZIP 43215 accepting Medicaid")
also belong to you: query facilities, return name, address, hours, cost_tier.
"""

analytics_agent = Agent(
    name="analytics",
    model=load_config().models.analytics,
    description=(
        "Answers data questions (comparisons, trends, counts, facility lookups) by writing "
        "and running guarded BigQuery SQL, returning charts and narratives."
    ),
    instruction=_INSTRUCTION,
    tools=[get_schema, run_bigquery, render_chart_spec],
)
