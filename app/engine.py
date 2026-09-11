import datetime as dt
import json
UNDER_V = 195.0      
CRIT_V = 185.0
OVER_V = 253.0
DROP_RATIO = 0.45    
IMBALANCE = 0.45     
REVERSE_TAMPER = 5   
TX_LOSS = 0.35       
def _bucket(now: dt.datetime) -> str:
    return now.strftime("%Y%m%d%H") + f"{(now.minute // 30) * 30:02d}"
def evaluate(snapshot: list[dict], all_specs: list[str], now: dt.datetime) -> list[dict]:
    alerts: list[dict] = []
    bucket = _bucket(now)
    seen = {r["meter_id"] for r in snapshot}
    by_tx: dict[str, dict] = {}
    for r in snapshot:
        by_tx.setdefault(r["transformer"], {"exp": 0.0, "act": 0.0, "feeder": r["feeder"]})
        by_tx[r["transformer"]]["exp"] += r["baseline_kw"]
        by_tx[r["transformer"]]["act"] += r["kw"]
    for r in snapshot:
        mid = r["meter_id"]
        if r["baseline_kw"] > 0.05 and r["kw"] < DROP_RATIO * r["baseline_kw"]:
            sev = "critical"
            title = f"Suspected bypass — {r['name']} drawing {int((1 - r['kw'] / r['baseline_kw']) * 100)}% below baseline"
            alerts.append({
                "key": f"bypass:{mid}:{bucket}", "kind": "bypass", "severity": sev,
                "meter_id": mid, "scope": "meter", "title": title,
                "evidence": {
                    "kw_now": r["kw"], "kw_baseline": r["baseline_kw"],
                    "drop_pct": round((1 - r["kw"] / r["baseline_kw"]) * 100, 1),
                    "voltage": r["voltage"], "cover_open": bool(r["flags"].get("cover_open")),
                    "transformer": r["transformer"],
                },
            })
        if r["voltage"] < CRIT_V:
            alerts.append({
                "key": f"undervolt:{mid}:{bucket}", "kind": "undervoltage", "severity": "critical",
                "meter_id": mid, "scope": "meter",
                "title": f"Dangerous undervoltage at {r['name']} — {r['voltage']} V (nominal 230 V)",
                "evidence": {"voltage": r["voltage"], "nominal": 230.0, "phases": r["phases"], "transformer": r["transformer"]},
            })
        elif r["voltage"] < UNDER_V:
            alerts.append({
                "key": f"undervolt:{mid}:{bucket}", "kind": "undervoltage", "severity": "warning",
                "meter_id": mid, "scope": "meter",
                "title": f"Sustained undervoltage at {r['name']} — {r['voltage']} V",
                "evidence": {"voltage": r["voltage"], "nominal": 230.0, "phases": r["phases"], "transformer": r["transformer"]},
            })
        elif r["voltage"] > OVER_V:
            alerts.append({
                "key": f"overvolt:{mid}:{bucket}", "kind": "overvoltage", "severity": "warning",
                "meter_id": mid, "scope": "meter",
                "title": f"Overvoltage at {r['name']} — {r['voltage']} V",
                "evidence": {"voltage": r["voltage"], "nominal": 230.0, "transformer": r["transformer"]},
            })
        pc = r.get("phase_current") or []
        if len(pc) == 3 and sum(pc) > 0:
            spread = (max(pc) - min(pc)) / (sum(pc) / 3)
            if spread > IMBALANCE:
                alerts.append({
                    "key": f"imbalance:{mid}:{bucket}", "kind": "imbalance", "severity": "warning",
                    "meter_id": mid, "scope": "meter",
                    "title": f"Phase imbalance at {r['name']} — {int(spread * 100)}% spread across L1/L2/L3",
                    "evidence": {"phase_current": pc, "spread": round(spread, 2), "transformer": r["transformer"]},
                })
        if r["reverse_events"] >= REVERSE_TAMPER:
            alerts.append({
                "key": f"tamper:{mid}:{bucket}", "kind": "tamper", "severity": "critical",
                "meter_id": mid, "scope": "meter",
                "title": f"Tamper pattern at {r['name']} — {r['reverse_events']} reverse-flow events",
                "evidence": {"reverse_events": r["reverse_events"], "cover_open": bool(r["flags"].get("cover_open")),
                             "kw_now": r["kw"], "transformer": r["transformer"]},
            })
    for spec_id in all_specs:
        if spec_id not in seen:
            alerts.append({
                "key": f"offline:{spec_id}:{bucket}", "kind": "offline", "severity": "warning",
                "meter_id": spec_id, "scope": "meter",
                "title": f"{spec_id} stopped reporting — meter offline or COMMS failure",
                "evidence": {"last_seen_check": now.isoformat() + "Z"},
            })
    for tx, d in by_tx.items():
        if d["exp"] > 0.2:
            loss = 1 - d["act"] / d["exp"]
            if loss > TX_LOSS:
                alerts.append({
                    "key": f"txloss:{tx}:{bucket}", "kind": "tx_loss", "severity": "critical",
                    "meter_id": None, "scope": tx,
                    "title": f"High losses on {tx} — {int(loss * 100)}% of delivered energy unaccounted",
                    "evidence": {"expected_kw": round(d["exp"], 2), "delivered_kw": round(d["act"], 2),
                                 "loss_pct": round(loss * 100, 1), "feeder": d["feeder"]},
                })
    return alerts
def recommended_action(kind: str, ev: dict) -> str:
    if kind == "bypass":
        return ("Dispatch a field team to inspect the meter seal and service line for a direct hook. "
                f"Baseline was {ev.get('kw_baseline')} kW and the meter now reports {ev.get('kw_now')} kW at "
                f"{ev.get('voltage')} V — a healthy installation does not drop like that while voltage holds.")
    if kind == "tamper":
        return ("Send an inspection crew today: reverse-flow events with the cover-open flag usually mean "
                "the meter has been opened or an export clamp is fitted. Photograph the seal before touching.")
    if kind in ("undervoltage", "overvoltage"):
        return ("Log a distribution-fault ticket: sustained voltage outside 195–253 V damages customer equipment. "
                "Check the transformer tap and neutral on that feeder.")
    if kind == "imbalance":
        return ("Rebalance single-phase customers across L1/L2/L3 at the distribution board — "
                "the spread pays back as lower neutral losses and fewer tripped breakers.")
    if kind == "offline":
        return ("Ping the meter over the AMI network; if it stays silent, schedule a SIM/antenna check — "
                "an unmonitored meter is an unguarded meter.")
    if kind == "tx_loss":
        return (f"Walk the {ev.get('feeder', '')} feeder at night with a clamp meter: losses of "
                f"{ev.get('loss_pct')}% on one transformer usually mean illegal connections upstream of meters.")
    return "Review the evidence and schedule an inspection."
