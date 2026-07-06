"""Deterministic Vega-Lite chart-spec builder (no LLM in the loop).

Reads rows stashed in session state by run_bigquery / run_forecast, writes the
finished spec back to state where main.py emits it as a `chart_spec` SSE event.
"""
from __future__ import annotations

import re
from typing import Any

from google.adk.tools import ToolContext

_MARKS = {"line": "line", "bar": "bar", "area": "area", "point": "point"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _field_type(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        v = row.get(field)
        if v is None:
            continue
        if isinstance(v, bool):
            return "nominal"
        if isinstance(v, (int, float)):
            return "quantitative"
        if isinstance(v, str) and _DATE_RE.match(v):
            return "temporal"
        return "nominal"
    return "nominal"


def render_chart_spec(
    chart_type: str,
    x_field: str,
    y_field: str,
    series_field: str = "",
    title: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Build a chart from the rows returned by the most recent query/forecast.

    Args:
        chart_type: one of line, bar, area, point.
        x_field: column for the x axis (must exist in the last result rows).
        y_field: numeric column for the y axis.
        series_field: optional column to color/split by.
        title: short chart title.

    Returns:
        {"ok": True} when the chart was attached to the response, else {"error": str}.
    """
    rows = tool_context.state.get("last_rows") or []
    if not rows:
        return {"error": "no query results available — run a query or forecast first"}
    for f in filter(None, [x_field, y_field, series_field]):
        if f not in rows[0]:
            return {"error": f"field '{f}' not in result columns {list(rows[0])}"}

    spec: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title or None,
        "width": "container",
        "height": 320,
        "data": {"values": rows},
        "mark": {"type": _MARKS.get(chart_type, "bar"), "tooltip": True},
        "encoding": {
            "x": {"field": x_field, "type": _field_type(rows, x_field)},
            "y": {"field": y_field, "type": "quantitative"},
        },
    }
    if series_field:
        spec["encoding"]["color"] = {"field": series_field, "type": "nominal"}

    # Forecast results carry interval bounds — add a confidence band layer.
    if {"lower_bound", "upper_bound"} <= set(rows[0]):
        band = {
            "mark": {"type": "errorband"},
            "encoding": {
                "x": spec["encoding"]["x"],
                "y": {"field": "lower_bound", "type": "quantitative", "title": y_field},
                "y2": {"field": "upper_bound"},
                **({"color": spec["encoding"]["color"]} if series_field else {}),
            },
        }
        line = {"mark": spec.pop("mark"), "encoding": spec.pop("encoding")}
        spec["layer"] = [band, line]

    tool_context.state["chart_spec"] = {
        "vega_lite": spec,
        "sql": tool_context.state.get("last_sql"),
    }
    return {"ok": True, "note": "chart attached to the response"}
