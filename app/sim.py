import datetime as dt
import hashlib
import math
import random
NOMINAL_V = 230.0
NETWORK = {
    "FEEDER-A": {"tf": ["TX-A1", "TX-A2"]},
    "FEEDER-B": {"tf": ["TX-B1"]},
}
METER_SPECS = [
    ("M-101", "Sabon Gari market row", "FEEDER-A", "TX-A1", "shop", 0.85, 120, 150),
    ("M-102", "Welding workshop 3", "FEEDER-A", "TX-A1", "industrial", 1.60, 210, 150),
    ("M-103", "Amina cold store", "FEEDER-A", "TX-A1", "commerce", 1.10, 300, 150),
    ("M-104", "Block 7 flats", "FEEDER-A", "TX-A1", "residential", 0.45, 390, 150),
    ("M-105", "Barber shop 12", "FEEDER-A", "TX-A1", "shop", 0.22, 480, 150),
    ("M-106", "Rice mill line B", "FEEDER-A", "TX-A2", "industrial", 2.10, 120, 300),
    ("M-107", "Chemist + clinic", "FEEDER-A", "TX-A2", "health", 0.55, 210, 300),
    ("M-108", "Mallam tea stall", "FEEDER-A", "TX-A2", "shop", 0.12, 300, 300),
    ("M-109", "Hostel block C", "FEEDER-A", "TX-A2", "residential", 0.70, 390, 300),
    ("M-110", "Phone repair kiosk", "FEEDER-A", "TX-A2", "shop", 0.10, 480, 300),
    ("M-201", "Grain dryer 1", "FEEDER-B", "TX-B1", "industrial", 1.80, 160, 450),
    ("M-202", "Primary school", "FEEDER-B", "TX-B1", "public", 0.40, 250, 450),
    ("M-203", "Tailor collective", "FEEDER-B", "TX-B1", "shop", 0.35, 340, 450),
    ("M-204", "Water pumping point", "FEEDER-B", "TX-B1", "utility", 1.20, 430, 450),
    ("M-205", "Musa duplex", "FEEDER-B", "TX-B1", "residential", 0.50, 520, 450),
    ("M-206", "Night market strip", "FEEDER-B", "TX-B1", "commerce", 0.95, 610, 450),
    ("M-207", "Borehole 2", "FEEDER-B", "TX-B1", "utility", 0.90, 700, 450),
    ("M-208", "Church annex", "FEEDER-B", "TX-B1", "public", 0.30, 790, 450),
]
def token_for(meter_id: str) -> str:
    return "gs_" + hashlib.sha256(f"gridsentry:{meter_id}".encode()).hexdigest()[:24]
def hour_shape(hour: int, kind: str) -> float:
    base = 0.35 + 0.65 * (0.5 + 0.5 * math.sin((hour - 6) / 24 * 2 * math.pi))
    if kind == "residential":
        peak = [0.5, 0.4, 0.35, 0.3, 0.35, 0.5, 0.7, 0.8, 0.7, 0.6, 0.6, 0.65,
                0.7, 0.7, 0.7, 0.75, 0.9, 1.15, 1.35, 1.4, 1.3, 1.1, 0.9, 0.65][hour]
    elif kind in ("industrial", "utility"):
        peak = [0.6, 0.6, 0.6, 0.6, 0.6, 0.7, 0.9, 1.1, 1.25, 1.3, 1.3, 1.25,
                1.2, 1.25, 1.3, 1.3, 1.2, 1.0, 0.8, 0.7, 0.65, 0.6, 0.6, 0.6][hour]
    elif kind in ("shop", "commerce"):
        peak = [0.3, 0.25, 0.2, 0.2, 0.2, 0.3, 0.5, 0.7, 0.9, 1.1, 1.2, 1.25,
                1.2, 1.15, 1.2, 1.25, 1.3, 1.25, 1.1, 0.9, 0.7, 0.55, 0.45, 0.35][hour]
    else:
        peak = [0.5, 0.45, 0.4, 0.4, 0.4, 0.5, 0.6, 0.8, 0.9, 0.9, 0.85, 0.8,
                0.8, 0.85, 0.9, 0.9, 0.85, 0.8, 0.85, 0.9, 0.85, 0.75, 0.65, 0.55][hour]
    return base * peak
def synth_meter(spec, now: dt.datetime, rng: random.Random, scenario: dict | None):
    mid, name, feeder, tx, kind, base, x, y = spec
    mult = hour_shape(now.hour, kind)
    kw = base * mult * (0.9 + 0.2 * rng.random())
    v = NOMINAL_V + rng.uniform(-2.5, 2.5)
    phases = [v + rng.uniform(-1.5, 1.5) for _ in range(3)]
    cur = (kw * 1000.0) / v
    phase_cur = [cur / 3 * (0.9 + 0.2 * rng.random()) for _ in range(3)]
    kwh_export = round(base * 24 * 30 * (0.8 + 0.4 * rng.random()), 2)
    reverse_events = 0 if rng.random() > 0.02 else 1
    flags: dict = {}
    if scenario:
        k = scenario["kind"]
        if k == "bypass" and scenario.get("meter_id") == mid:
            kw *= 0.10
            phase_cur = [c * 0.12 for c in phase_cur]
            flags["cover_open"] = True
        elif k == "sag" and scenario.get("meter_id") in (None, mid) or (k == "sag" and scenario.get("feeder") == feeder):
            v *= 0.78
            phases = [p * 0.78 for p in phases]
        elif k == "imbalance" and scenario.get("meter_id") == mid:
            phase_cur = [cur * 0.8, cur * 0.15, cur * 0.05]
        elif k == "offline" and scenario.get("meter_id") == mid:
            return None
        elif k == "tamper" and scenario.get("meter_id") == mid:
            reverse_events += 14
            flags["cover_open"] = True
    reading = {
        "meter_id": mid,
        "ts": now.isoformat() + "Z",
        "voltage": round(v, 1),
        "current": round(cur, 2),
        "kw": round(kw, 3),
        "kwh_export": kwh_export,
        "reverse_events": reverse_events,
        "phases": [round(p, 1) for p in phases],
        "phase_current": [round(c, 2) for c in phase_cur],
        "flags": flags,
    }
    return reading
def network_tick(now: dt.datetime, scenarios: list[dict]) -> list[dict]:
    seed = int(now.timestamp() // 4)
    out = []
    for spec in METER_SPECS:
        rng = random.Random(seed + int(spec[0].split("-")[1]))
        scen = None
        for s in scenarios:
            if s.get("meter_id") == spec[0]:
                scen = s
                break
            if s.get("kind") == "sag" and s.get("feeder") in (None, spec[2]):
                scen = s
                break
        r = synth_meter(spec, now, rng, scen)
        if r:
            r["name"] = spec[1]
            r["feeder"] = spec[2]
            r["transformer"] = spec[3]
            r["kind"] = spec[4]
            r["baseline_kw"] = round(spec[5] * hour_shape(now.hour, spec[4]), 3)
            r["x"] = spec[6]
            r["y"] = spec[7]
            out.append(r)
    return out
def live_scenarios(rows) -> list[dict]:
    now = dt.datetime.utcnow()
    out = []
    for s in rows:
        if not s.active:
            continue
        age = (now - s.started_at).total_seconds()
        if age > s.ttl_s:
            s.active = False
            continue
        out.append({"kind": s.kind, "meter_id": s.meter_id, "feeder": s.feeder, "age_s": int(age)})
    return out
def history_series(meter_spec, hours: int = 24, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.utcnow()
    out = []
    mid, name, feeder, tx, kind, base, x, y = meter_spec
    for h in range(hours):
        t = now - dt.timedelta(hours=hours - 1 - h)
        rng = random.Random(int(t.timestamp() // 3600) + int(mid.split("-")[1]))
        kw = base * hour_shape(t.hour, kind) * (0.92 + 0.16 * rng.random())
        v = NOMINAL_V + rng.uniform(-2.0, 2.0)
        out.append({"hour": t.strftime("%H:00"), "kw": round(kw, 3), "voltage": round(v, 1)})
    return out
