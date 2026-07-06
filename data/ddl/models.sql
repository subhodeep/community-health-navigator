-- BigQuery ML models — refreshed weekly by functions/refresh_models.
CREATE OR REPLACE MODEL community_health.demand_forecast
OPTIONS(
  model_type = 'ARIMA_PLUS',
  time_series_timestamp_col = 'date',
  time_series_data_col = 'visits',
  time_series_id_col = 'district'
) AS
SELECT
  u.date,
  f.district,
  SUM(u.visits) AS visits
FROM community_health.utilization_daily u
JOIN community_health.facilities f ON u.facility_id = f.facility_id
GROUP BY u.date, f.district;
