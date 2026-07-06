-- BigQuery DDL — dataset: community_health
-- Reference schema; the ingest function loads JSONL with autodetect, which
-- produces these shapes. Run manually only if you want tables ahead of data.

CREATE SCHEMA IF NOT EXISTS community_health;

CREATE TABLE IF NOT EXISTS community_health.facilities (
  facility_id STRING NOT NULL,
  name STRING,
  category STRING,               -- clinic | hospital | pharmacy | community_center
  services ARRAY<STRING>,        -- 'flu_shot','dental','cardiology','screening',...
  address STRING,
  zip STRING,
  district STRING,               -- D1..D6
  lat FLOAT64,
  lon FLOAT64,
  hours STRING,                  -- JSON text, e.g. {"mon_fri":"8:00-18:00","sat":"9:00-13:00"}
  accepts ARRAY<STRING>,         -- 'medicaid','uninsured','sliding_scale','private'
  cost_tier STRING               -- free | low | standard
);

CREATE TABLE IF NOT EXISTS community_health.utilization_daily (
  date DATE,
  facility_id STRING,
  visit_type STRING,             -- er | urgent | primary | wellness
  visits INT64,
  avg_wait_minutes FLOAT64
);

CREATE TABLE IF NOT EXISTS community_health.environment_daily (
  date DATE,
  district STRING,
  aqi INT64,
  pollen_index INT64,
  heat_index FLOAT64
);

CREATE TABLE IF NOT EXISTS community_health.program_enrollment (
  date DATE,
  program_id STRING,
  program_name STRING,
  district STRING,
  enrollments INT64,
  capacity INT64
);
