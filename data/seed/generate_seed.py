"""Generate deterministic synthetic seed data as JSONL for BigQuery ingestion.

Usage:  python data/seed/generate_seed.py
Output: data/seed/out/{facilities,utilization_daily,environment_daily,program_enrollment}.jsonl

Fictional city: Franklin Ridge (districts D1..D6). Includes a deliberate demand
anomaly in district D3 during June 2026 so anomaly detection has something to find.
"""
from __future__ import annotations

import datetime
import json
import math
import random
from pathlib import Path

random.seed(42)
OUT = Path(__file__).parent / "out"
END_DATE = datetime.date(2026, 6, 30)
DAYS = 365
DISTRICTS = ["D1", "D2", "D3", "D4", "D5", "D6"]

SERVICE_POOL = {
    "clinic": ["primary_care", "flu_shot", "screening", "dental", "counseling", "pediatrics"],
    "hospital": ["er", "cardiology", "primary_care", "screening", "imaging"],
    "pharmacy": ["flu_shot", "vaccines", "prescriptions"],
    "community_center": ["wellness_program", "screening", "counseling", "nutrition"],
}
ACCEPT_POOL = ["medicaid", "uninsured", "sliding_scale", "private"]
VISIT_TYPES = {
    "clinic": ["urgent", "primary", "wellness"],
    "hospital": ["er", "urgent", "primary"],
    "pharmacy": ["wellness"],
    "community_center": ["wellness"],
}
BASE_VISITS = {"er": 55, "urgent": 40, "primary": 30, "wellness": 15}

NAMES = {
    "clinic": ["{d} Family Health Clinic", "Riverside Clinic {n}", "Northgate Community Clinic"],
    "hospital": ["Franklin Ridge General", "St. Amara Medical Center"],
    "pharmacy": ["Maple Pharmacy {n}", "CarePoint Pharmacy {n}"],
    "community_center": ["{d} Wellness Center", "Unity Community Center {n}"],
}


def make_facilities() -> list[dict]:
    facilities = []
    idx = 0
    plan = [("hospital", 1), ("clinic", 3), ("pharmacy", 2), ("community_center", 1)]
    for di, district in enumerate(DISTRICTS):
        for category, count in plan:
            if category == "hospital" and district not in ("D1", "D3", "D5"):
                continue  # 3 hospitals citywide
            for c in range(count):
                idx += 1
                template = random.choice(NAMES[category])
                name = template.format(d=district, n=idx)
                services = sorted(
                    random.sample(SERVICE_POOL[category], k=min(4, len(SERVICE_POOL[category])))
                )
                accepts = sorted(random.sample(ACCEPT_POOL, k=random.randint(2, 4)))
                facilities.append(
                    {
                        "facility_id": f"F{idx:03d}",
                        "name": name,
                        "category": category,
                        "services": services,
                        "address": f"{100 + idx * 7} {district} Main St, Franklin Ridge",
                        "zip": f"432{di:02d}",
                        "district": district,
                        "lat": round(39.90 + di * 0.03 + random.uniform(-0.01, 0.01), 5),
                        "lon": round(-83.05 + c * 0.02 + random.uniform(-0.01, 0.01), 5),
                        "hours": json.dumps(
                            {"mon_fri": "8:00-18:00", "sat": "9:00-13:00", "sun": "closed"}
                        ),
                        "accepts": accepts,
                        "cost_tier": random.choice(["free", "low", "low", "standard"]),
                    }
                )
    return facilities


def seasonality(day: datetime.date) -> float:
    # Winter respiratory bump (peaks late December), mild summer dip.
    doy = day.timetuple().tm_yday
    return 1.0 + 0.30 * math.cos(2 * math.pi * (doy - 355) / 365)


def make_utilization(facilities: list[dict]) -> list[dict]:
    rows = []
    for f in facilities:
        for offset in range(DAYS):
            day = END_DATE - datetime.timedelta(days=DAYS - 1 - offset)
            weekday_factor = 0.6 if day.weekday() >= 5 else 1.0
            anomaly = 1.8 if (f["district"] == "D3" and day >= datetime.date(2026, 6, 10)) else 1.0
            for vt in VISIT_TYPES[f["category"]]:
                base = BASE_VISITS[vt] * seasonality(day) * weekday_factor * anomaly
                visits = max(0, int(random.gauss(base, base * 0.15)))
                rows.append(
                    {
                        "date": day.isoformat(),
                        "facility_id": f["facility_id"],
                        "visit_type": vt,
                        "visits": visits,
                        "avg_wait_minutes": round(max(5.0, visits * random.uniform(0.5, 0.9)), 1),
                    }
                )
    return rows


def make_environment() -> list[dict]:
    rows = []
    for district in DISTRICTS:
        for offset in range(DAYS):
            day = END_DATE - datetime.timedelta(days=DAYS - 1 - offset)
            summer = max(0.0, math.sin(math.pi * (day.timetuple().tm_yday - 120) / 180))
            aqi = int(random.gauss(45 + 40 * summer, 12))
            if district == "D3" and day >= datetime.date(2026, 6, 10):
                aqi += 60  # smoke event driving the demand anomaly
            rows.append(
                {
                    "date": day.isoformat(),
                    "district": district,
                    "aqi": max(10, aqi),
                    "pollen_index": max(0, int(random.gauss(30 + 50 * summer, 15))),
                    "heat_index": round(random.gauss(15 + 18 * summer, 4), 1),
                }
            )
    return rows


def make_programs() -> list[dict]:
    programs = [
        ("P01", "Healthy Hearts Screening"),
        ("P02", "Diabetes Prevention Program"),
        ("P03", "Community Flu Shot Drive"),
        ("P04", "Maternal Wellness Visits"),
        ("P05", "Senior Mobility Classes"),
        ("P06", "Youth Nutrition Workshops"),
    ]
    rows = []
    day = END_DATE - datetime.timedelta(days=DAYS - 1)
    while day.weekday() != 0:
        day += datetime.timedelta(days=1)
    while day <= END_DATE:
        for pid, pname in programs:
            for district in DISTRICTS:
                capacity = random.choice([30, 40, 50])
                rows.append(
                    {
                        "date": day.isoformat(),
                        "program_id": pid,
                        "program_name": pname,
                        "district": district,
                        "enrollments": min(capacity, max(0, int(random.gauss(capacity * 0.7, 8)))),
                        "capacity": capacity,
                    }
                )
        day += datetime.timedelta(days=7)
    return rows


def write(name: str, rows: list[dict]) -> None:
    path = OUT / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"{path.name}: {len(rows)} rows")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    facilities = make_facilities()
    write("facilities", facilities)
    write("utilization_daily", make_utilization(facilities))
    write("environment_daily", make_environment())
    write("program_enrollment", make_programs())
