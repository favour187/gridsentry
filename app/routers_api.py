import csv
import datetime as dt
import io
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import sim
from .db import SessionLocal
from .models import Alert, Meter, Reading, Scenario
from .engine import evaluate, fleet_health, meter_risk
from .ai_skills import investigate

router = APIRouter(prefix="/api")

SCENARIO_KINDS = ("bypass", "sag", "imbalance", "offline", "tamper",
                  "neutral", "freq", "overload", "outage")

# topology lookup for group-level rules (meters missing from a snapshot still
# need to be attributable to a feeder)
SPEC_META = {s[0]: {"feeder": s[2], "transformer": s[3]} for s in sim.METER_SPECS}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed(db: Session):
    if db.query(Meter).count():
        return
    for mid, name, feeder, tx, kind, base, x, y in sim.METER_SPECS:
        db.add(Meter(id=mid, name=name, feeder=feeder, transformer=tx, kind=kind,
                     baseline_kwh_h=base, token=sim.token_for(mid), x=x, y=y))
    db.commit()


class ScenarioIn(BaseModel):
    kind: str
    meter_id: str | None = None
    feeder: str | None = None


class IngestIn(BaseModel):
    voltage: float
    current: float
    kw: float
    kwh_export: float = 0.0
    reverse_events: int = 0
    freq_hz: float | None = None
    pf: float | None = None
    phases: list[float] = [230.0, 230.0, 230.0]
    phase_current: list[float] = [0.0, 0.0, 0.0]
    cover_open: bool = False


def _alert_payload(a: Alert) -> dict:
    return {
        "id": a.id, "kind": a.kind, "severity": a.severity, "meter_id": a.meter_id,
        "scope": a.scope, "title": a.title, "evidence": json.loads(a.evidence or "{}"),
        "status": a.status, "created_at": a.created_at.isoformat() + "Z",
        "updated_at": a.updated_at.isoformat() + "Z",
    }


def _status_for(r: dict) -> str:
    if r["voltage"] < sim.NOMINAL_V * 0.85 or r["voltage"] > sim.NOMINAL_V * 1.1:
        return "fault"
    f = r.get("freq_hz")
    if f is not None and abs(f - 50.0) > 0.5:
        return "fault"
    return "ok"


@router.get("/health")
def health():
    return {"status": "ok", "service": "gridsentry", "version": "2.0",
            "time": dt.datetime.utcnow().isoformat() + "Z"}


def _fresh_alerts(db: Session, snapshot, now):
    """Evaluate a snapshot and upsert the resulting alerts."""
    specs = [s[0] for s in sim.METER_SPECS]
    fresh = evaluate(snapshot, specs, now, spec_meta=SPEC_META)
    for a in fresh:
        row = db.query(Alert).filter(Alert.key == a["key"]).first()
        if row:
            row.evidence = json.dumps(a["evidence"])
            row.updated_at = now
            if row.status == "resolved":
                row.status = "open"
        else:
            row = Alert(key=a["key"], kind=a["kind"], severity=a["severity"], meter_id=a["meter_id"],
                        scope=a["scope"], title=a["title"], evidence=json.dumps(a["evidence"]))
            db.add(row)
    db.commit()
    return fresh


@router.get("/live")
def live(db: Session = Depends(get_db)):
    now = dt.datetime.utcnow()
    scen = sim.live_scenarios(db.query(Scenario).filter(Scenario.active == True).all())
    db.commit()
    snapshot = sim.network_tick(now, scen)
    seed(db)
    fresh = _fresh_alerts(db, snapshot, now)
    open_alerts = db.query(Alert).filter(Alert.status != "resolved").order_by(Alert.created_at.desc()).all()
    alerts = [_alert_payload(a) for a in open_alerts]

    expected = sum(r["baseline_kw"] for r in snapshot)
    delivered = sum(r["kw"] for r in snapshot)

    risks = {mid: meter_risk(fresh, mid) for mid in SPEC_META}
    at_risk = sorted(
        ({"meter_id": mid, "score": v["score"], "reasons": v["reasons"]}
         for mid, v in risks.items() if v["score"] > 0),
        key=lambda x: -x["score"],
    )
    meters = []
    for r in snapshot:
        risk = risks.get(r["meter_id"], {"score": 0, "reasons": []})
        meters.append({**{k: r[k] for k in ("meter_id", "name", "feeder", "transformer", "kind", "x", "y",
                                            "voltage", "current", "kw", "baseline_kw", "reverse_events",
                                            "phase_current", "phases", "flags", "freq_hz", "pf")},
                       "status": _status_for(r), "risk": risk["score"], "risk_reasons": risk["reasons"],
                       "ts": r["ts"]})
    freqs = [r["freq_hz"] for r in snapshot if r.get("freq_hz")]
    return {
        "now": now.isoformat() + "Z",
        "meters": meters,
        "alerts": alerts[:80],
        "scenarios": scen,
        "at_risk": at_risk[:8],
        "kpis": {
            "delivered_kw": round(delivered, 2),
            "expected_kw": round(expected, 2),
            "loss_pct": round((1 - delivered / expected) * 100, 1) if expected > 0 else 0.0,
            "online": len(snapshot),
            "total": len(SPEC_META),
            "alerts_open": len(alerts),
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
            "health": fleet_health(risks, len(SPEC_META)),
            "grid_freq_hz": round(sum(freqs) / len(freqs), 2) if freqs else None,
        },
    }


@router.get("/network")
def network(db: Session = Depends(get_db)):
    seed(db)
    meters = db.query(Meter).all()
    feeders = {}
    for m in meters:
        feeders.setdefault(m.feeder, {"transformers": {}, "meters": 0})
        feeders[m.feeder]["transformers"].setdefault(m.transformer, [])
        feeders[m.feeder]["transformers"][m.transformer].append(m.id)
        feeders[m.feeder]["meters"] += 1
    return {"feeders": feeders, "nominal_v": sim.NOMINAL_V}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """Incident analytics: counts by kind/severity, lifecycle, MTTR, 24 h trend."""
    seed(db)
    all_rows = db.query(Alert).all()
    by_kind: dict[str, dict] = {}
    by_status = {"open": 0, "ack": 0, "resolved": 0}
    by_severity = {"critical": 0, "warning": 0}
    mttr_minutes, resolved_count = [], 0
    now = dt.datetime.utcnow()
    for a in all_rows:
        k = by_kind.setdefault(a.kind, {"kind": a.kind, "open": 0, "resolved": 0,
                                        "critical": 0, "warning": 0})
        k["critical" if a.severity == "critical" else "warning"] += 1
        if a.status == "resolved":
            k["resolved"] += 1
            by_status["resolved"] += 1
            mttr_minutes.append(max(0, (a.updated_at - a.created_at).total_seconds() / 60))
            resolved_count += 1
        else:
            k["open"] += 1
            by_status["ack" if a.status == "ack" else "open"] += 1
        by_severity[a.severity if a.severity in by_severity else "warning"] += 1
    trend = []
    for h in range(23, -1, -1):
        t0 = now - dt.timedelta(hours=h + 1)
        t1 = now - dt.timedelta(hours=h)
        n = db.query(Alert).filter(Alert.created_at >= t0, Alert.created_at < t1).count()
        trend.append({"hour": t1.strftime("%H:00"), "alerts": n})
    total = len(all_rows)
    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_kind": sorted(by_kind.values(), key=lambda x: -(x["open"] + x["resolved"])),
        "resolution_rate_pct": round(100 * resolved_count / total, 1) if total else 0.0,
        "mttr_minutes": round(sum(mttr_minutes) / len(mttr_minutes), 1) if mttr_minutes else None,
        "trend_24h": trend,
    }


@router.get("/incidents.csv")
def incidents_csv(db: Session = Depends(get_db)):
    seed(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "kind", "severity", "meter_or_scope", "status", "title",
                "evidence", "created_at_utc", "updated_at_utc"])
    for a in db.query(Alert).order_by(Alert.created_at.desc()).limit(5000).all():
        w.writerow([a.id, a.kind, a.severity, a.meter_id or a.scope, a.status, a.title,
                    a.evidence, a.created_at.isoformat() + "Z", a.updated_at.isoformat() + "Z"])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=gridsentry-incidents.csv"})


@router.get("/devices")
def devices(db: Session = Depends(get_db)):
    seed(db)
    return {"devices": [{"meter_id": m.id, "name": m.name, "token": m.token, "feeder": m.feeder,
                         "transformer": m.transformer} for m in db.query(Meter).order_by(Meter.id).all()]}


@router.get("/meters/{meter_id}")
def meter_detail(meter_id: str, db: Session = Depends(get_db)):
    spec = next((s for s in sim.METER_SPECS if s[0] == meter_id), None)
    if not spec:
        raise HTTPException(404, "meter not found")
    return {"meter_id": meter_id, "name": spec[1], "feeder": spec[2], "transformer": spec[3],
            "kind": spec[4], "history": sim.history_series(spec)}


@router.post("/scenarios")
def start_scenario(body: ScenarioIn, db: Session = Depends(get_db)):
    if body.kind not in SCENARIO_KINDS:
        raise HTTPException(400, f"unknown scenario kind; choose from {SCENARIO_KINDS}")
    s = Scenario(kind=body.kind, meter_id=body.meter_id, feeder=body.feeder)
    db.add(s)
    db.commit()
    return {"ok": True, "scenario": {"id": s.id, "kind": s.kind, "meter_id": s.meter_id, "feeder": s.feeder}}


@router.get("/scenarios")
def list_scenarios(db: Session = Depends(get_db)):
    sim.live_scenarios(db.query(Scenario).all())
    db.commit()
    return {"active": [{"id": s.id, "kind": s.kind, "meter_id": s.meter_id, "started_at": s.started_at.isoformat() + "Z"}
                       for s in db.query(Scenario).filter(Scenario.active == True).all()]}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404)
    a.status = "ack" if a.status == "open" else a.status
    a.updated_at = dt.datetime.utcnow()
    db.commit()
    return _alert_payload(a)


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404)
    a.status = "resolved"
    a.updated_at = dt.datetime.utcnow()
    db.commit()
    return _alert_payload(a)


@router.post("/investigate/{alert_id}")
def investigate_alert(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404)
    reading = None
    if a.meter_id:
        scen = sim.live_scenarios(db.query(Scenario).filter(Scenario.active == True).all())
        db.commit()
        for r in sim.network_tick(dt.datetime.utcnow(), scen):
            if r["meter_id"] == a.meter_id:
                reading = r
                break
    return investigate(a, reading)


@router.post("/ingest/{meter_id}")
def ingest(meter_id: str, body: IngestIn, authorization: str = Header(default=""),
           db: Session = Depends(get_db)):
    m = db.get(Meter, meter_id)
    if not m:
        raise HTTPException(404, "unknown meter")
    token = authorization.replace("Bearer ", "").strip()
    if token != m.token:
        raise HTTPException(401, "bad device token")
    now = dt.datetime.utcnow()
    db.add(Reading(meter_id=meter_id, ts=now, voltage=body.voltage, current=body.current,
                   kw=body.kw, kwh_export=body.kwh_export, reverse_events=body.reverse_events,
                   phases=json.dumps(body.phases)))
    spec = next(s for s in sim.METER_SPECS if s[0] == meter_id)
    reading = {"meter_id": meter_id, "name": spec[1], "feeder": spec[2], "transformer": spec[3],
               "kw": body.kw, "voltage": body.voltage, "baseline_kw": spec[5],
               "reverse_events": body.reverse_events, "freq_hz": body.freq_hz, "pf": body.pf,
               "phase_current": body.phase_current,
               "flags": {"cover_open": body.cover_open}}
    fresh = evaluate([reading], [meter_id], now, spec_meta=SPEC_META)
    raised = []
    for a in fresh:
        row = db.query(Alert).filter(Alert.key == a["key"]).first()
        if not row:
            row = Alert(key=a["key"], kind=a["kind"], severity=a["severity"], meter_id=meter_id,
                        scope=a["scope"], title=a["title"], evidence=json.dumps(a["evidence"]))
            db.add(row)
            raised.append(a["kind"])
    db.commit()
    max_id = db.query(func.max(Reading.id)).scalar() or 0
    if max_id > 500:
        db.query(Reading).filter(Reading.id <= max_id - 500).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "alerts_raised": raised}
