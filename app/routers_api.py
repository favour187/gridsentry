import datetime as dt
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from . import sim
from .db import SessionLocal, engine
from .models import Alert, Meter, Reading, Scenario
from .engine import evaluate
from .ai_skills import investigate
router = APIRouter(prefix="/api")
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
    return "ok"
@router.get("/health")
def health():
    return {"status": "ok", "service": "gridsentry", "time": dt.datetime.utcnow().isoformat() + "Z"}
@router.get("/live")
def live(db: Session = Depends(get_db)):
    now = dt.datetime.utcnow()
    scen = sim.live_scenarios(db.query(Scenario).filter(Scenario.active == True).all())  
    db.commit()
    snapshot = sim.network_tick(now, scen)
    seed(db)
    specs = [s[0] for s in sim.METER_SPECS]
    fresh = evaluate(snapshot, specs, now)
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
    open_alerts = db.query(Alert).filter(Alert.status != "resolved").order_by(Alert.created_at.desc()).all()
    alerts = [_alert_payload(a) for a in open_alerts]
    expected = sum(r["baseline_kw"] for r in snapshot)
    delivered = sum(r["kw"] for r in snapshot)
    meters = []
    for r in snapshot:
        meters.append({**{k: r[k] for k in ("meter_id", "name", "feeder", "transformer", "kind", "x", "y",
                                            "voltage", "current", "kw", "baseline_kw", "reverse_events",
                                            "phase_current", "phases", "flags")},
                       "status": _status_for(r), "ts": r["ts"]})
    return {
        "now": now.isoformat() + "Z",
        "meters": meters,
        "alerts": alerts[:80],
        "scenarios": scen,
        "kpis": {
            "delivered_kw": round(delivered, 2),
            "expected_kw": round(expected, 2),
            "loss_pct": round((1 - delivered / expected) * 100, 1) if expected > 0 else 0.0,
            "online": len(snapshot),
            "total": len(specs),
            "alerts_open": len(alerts),
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
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
    if body.kind not in ("bypass", "sag", "imbalance", "offline", "tamper"):
        raise HTTPException(400, "unknown scenario kind")
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
               "reverse_events": body.reverse_events,
               "phase_current": body.phase_current,
               "flags": {"cover_open": body.cover_open}}
    fresh = evaluate([reading], [meter_id], now)
    raised = []
    for a in fresh:
        row = db.query(Alert).filter(Alert.key == a["key"]).first()
        if not row:
            row = Alert(key=a["key"], kind=a["kind"], severity=a["severity"], meter_id=meter_id,
                        scope=a["scope"], title=a["title"], evidence=json.dumps(a["evidence"]))
            db.add(row)
            raised.append(a["kind"])
    db.commit()
    from sqlalchemy import func
    max_id = db.query(func.max(Reading.id)).scalar() or 0
    if max_id > 500:
        db.query(Reading).filter(Reading.id <= max_id - 500).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "alerts_raised": raised}
