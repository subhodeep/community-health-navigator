"""ForecastAgent — parameterized BQML forecasting (Flow C)."""
from google.adk.agents import Agent

from shared.config import load_config
from tools.charts import render_chart_spec
from tools.forecast import run_forecast

_INSTRUCTION = """You produce forward-looking projections of community health metrics.

Workflow:
1. Extract (metric, horizon_days) from the request. Supported metric: 'visits'
   (daily clinic visit demand per district). Default horizon: 28 days.
2. Call run_forecast. If it returns UnsupportedMetric, tell the user what CAN be
   forecast instead — do not improvise numbers.
3. Call render_chart_spec(chart_type='line', x_field='date', y_field='forecast_visits',
   series_field='district') so the confidence-band chart is attached.
4. Narrate in 2-4 sentences: overall trend, districts with the highest projected
   demand, and ALWAYS this caveat: the forecast comes from an ARIMA_PLUS model over
   ~12 months of history and shows a 90% confidence interval, not a guarantee.
"""

forecast_agent = Agent(
    name="forecast",
    model=load_config().models.router,
    description="Forecasts clinic visit demand by district (BigQuery ML ARIMA_PLUS) with confidence bands.",
    instruction=_INSTRUCTION,
    tools=[run_forecast, render_chart_spec],
)
