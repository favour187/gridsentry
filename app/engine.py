import datetime as dt
UNDER_V = 195.0
CRIT_V = 185.0
OVER_V = 253.0
DROP_RATIO = 0.45
IMBALANCE = 0.45
REVERSE_TAMPER = 5
TX_LOSS = 0.35
NEUTRAL_SPREAD = 14.0
FREQ_NOMINAL = 50.0
FREQ_WARN = 0.3
FREQ_CRIT = 0.5
LOW_PF = 0.6
OVERLOAD_WARN = 0.9
OVERLOAD_CRIT = 1.05
OUTAGE_RATIO = 0.6
TX_CAPACITY = {'TX-A1': 6.0, 'TX-A2': 5.0, 'TX-B1': 11.0}

def _bucket(now: dt.datetime) -> str:
    return now.strftime('%Y%m%d%H') + f'{now.minute // 30 * 30:02d}'

def evaluate(snapshot: list[dict], all_specs: list[str], now: dt.datetime, spec_meta: dict | None=None) -> list[dict]:
    alerts: list[dict] = []
    bucket = _bucket(now)
    seen = {r['meter_id'] for r in snapshot}
    by_tx: dict[str, dict] = {}
    for r in snapshot:
        by_tx.setdefault(r['transformer'], {'exp': 0.0, 'act': 0.0, 'feeder': r['feeder']})
        by_tx[r['transformer']]['exp'] += r['baseline_kw']
        by_tx[r['transformer']]['act'] += r['kw']
    for r in snapshot:
        mid = r['meter_id']
        if r['baseline_kw'] > 0.05 and r['kw'] < DROP_RATIO * r['baseline_kw']:
            title = f"Suspected bypass — {r['name']} drawing {int((1 - r['kw'] / r['baseline_kw']) * 100)}% below baseline"
            alerts.append({'key': f'bypass:{mid}:{bucket}', 'kind': 'bypass', 'severity': 'critical', 'meter_id': mid, 'scope': 'meter', 'title': title, 'evidence': {'kw_now': r['kw'], 'kw_baseline': r['baseline_kw'], 'drop_pct': round((1 - r['kw'] / r['baseline_kw']) * 100, 1), 'voltage': r['voltage'], 'cover_open': bool(r['flags'].get('cover_open')), 'transformer': r['transformer']}})
        if r['voltage'] < CRIT_V:
            alerts.append({'key': f'undervolt:{mid}:{bucket}', 'kind': 'undervoltage', 'severity': 'critical', 'meter_id': mid, 'scope': 'meter', 'title': f"Dangerous undervoltage at {r['name']} — {r['voltage']} V (nominal 230 V)", 'evidence': {'voltage': r['voltage'], 'nominal': 230.0, 'phases': r['phases'], 'transformer': r['transformer']}})
        elif r['voltage'] < UNDER_V:
            alerts.append({'key': f'undervolt:{mid}:{bucket}', 'kind': 'undervoltage', 'severity': 'warning', 'meter_id': mid, 'scope': 'meter', 'title': f"Sustained undervoltage at {r['name']} — {r['voltage']} V", 'evidence': {'voltage': r['voltage'], 'nominal': 230.0, 'phases': r['phases'], 'transformer': r['transformer']}})
        elif r['voltage'] > OVER_V:
            alerts.append({'key': f'overvolt:{mid}:{bucket}', 'kind': 'overvoltage', 'severity': 'warning', 'meter_id': mid, 'scope': 'meter', 'title': f"Overvoltage at {r['name']} — {r['voltage']} V", 'evidence': {'voltage': r['voltage'], 'nominal': 230.0, 'transformer': r['transformer']}})
        pc = r.get('phase_current') or []
        if len(pc) == 3 and sum(pc) > 0:
            spread = (max(pc) - min(pc)) / (sum(pc) / 3)
            if spread > IMBALANCE:
                alerts.append({'key': f'imbalance:{mid}:{bucket}', 'kind': 'imbalance', 'severity': 'warning', 'meter_id': mid, 'scope': 'meter', 'title': f"Phase imbalance at {r['name']} — {int(spread * 100)}% spread across L1/L2/L3", 'evidence': {'phase_current': pc, 'spread': round(spread, 2), 'transformer': r['transformer']}})
        if r['reverse_events'] >= REVERSE_TAMPER:
            alerts.append({'key': f'tamper:{mid}:{bucket}', 'kind': 'tamper', 'severity': 'critical', 'meter_id': mid, 'scope': 'meter', 'title': f"Tamper pattern at {r['name']} — {r['reverse_events']} reverse-flow events", 'evidence': {'reverse_events': r['reverse_events'], 'cover_open': bool(r['flags'].get('cover_open')), 'kw_now': r['kw'], 'transformer': r['transformer']}})
        phases = r.get('phases') or []
        if len(phases) == 3:
            v_spread = max(phases) - min(phases)
            if v_spread > NEUTRAL_SPREAD:
                alerts.append({'key': f'neutral:{mid}:{bucket}', 'kind': 'neutral_tamper', 'severity': 'critical', 'meter_id': mid, 'scope': 'meter', 'title': f"Neutral/earth tamper suspect at {r['name']} — {v_spread:.0f} V phase split", 'evidence': {'phase_voltages': phases, 'voltage_split_v': round(v_spread, 1), 'cover_open': bool(r['flags'].get('cover_open')), 'transformer': r['transformer']}})
        freq = r.get('freq_hz')
        if freq is not None:
            dev = abs(freq - FREQ_NOMINAL)
            if dev > FREQ_CRIT:
                alerts.append({'key': f'frequency:{mid}:{bucket}', 'kind': 'frequency', 'severity': 'critical', 'meter_id': mid, 'scope': 'meter', 'title': f"Grid-frequency emergency at {r['name']} — {freq:.2f} Hz", 'evidence': {'freq_hz': round(freq, 2), 'nominal_hz': FREQ_NOMINAL, 'deviation_hz': round(dev, 2), 'feeder': r['feeder']}})
            elif dev > FREQ_WARN:
                alerts.append({'key': f'frequency:{mid}:{bucket}', 'kind': 'frequency', 'severity': 'warning', 'meter_id': mid, 'scope': 'meter', 'title': f"Frequency excursion at {r['name']} — {freq:.2f} Hz", 'evidence': {'freq_hz': round(freq, 2), 'nominal_hz': FREQ_NOMINAL, 'deviation_hz': round(dev, 2), 'feeder': r['feeder']}})
        pf = r.get('pf')
        if pf is not None and r['kw'] > 0.05 and (pf < LOW_PF):
            alerts.append({'key': f'lowpf:{mid}:{bucket}', 'kind': 'low_pf', 'severity': 'warning', 'meter_id': mid, 'scope': 'meter', 'title': f"Power factor collapse at {r['name']} — PF {pf:.2f}", 'evidence': {'power_factor': round(pf, 2), 'kw_now': r['kw'], 'transformer': r['transformer']}})
    for spec_id in all_specs:
        if spec_id not in seen:
            alerts.append({'key': f'offline:{spec_id}:{bucket}', 'kind': 'offline', 'severity': 'warning', 'meter_id': spec_id, 'scope': 'meter', 'title': f'{spec_id} stopped reporting — meter offline or COMMS failure', 'evidence': {'last_seen_check': now.isoformat() + 'Z'}})
    for tx, d in by_tx.items():
        if d['exp'] > 0.2:
            loss = 1 - d['act'] / d['exp']
            if loss > TX_LOSS:
                alerts.append({'key': f'txloss:{tx}:{bucket}', 'kind': 'tx_loss', 'severity': 'critical', 'meter_id': None, 'scope': tx, 'title': f'High losses on {tx} — {int(loss * 100)}% of delivered energy unaccounted', 'evidence': {'expected_kw': round(d['exp'], 2), 'delivered_kw': round(d['act'], 2), 'loss_pct': round(loss * 100, 1), 'feeder': d['feeder']}})
    for tx, d in by_tx.items():
        cap = TX_CAPACITY.get(tx)
        if cap and d['act'] >= OVERLOAD_WARN * cap:
            loading = d['act'] / cap
            sev = 'critical' if loading >= OVERLOAD_CRIT else 'warning'
            alerts.append({'key': f'overload:{tx}:{bucket}', 'kind': 'overload', 'severity': sev, 'meter_id': None, 'scope': tx, 'title': f"{tx} {('critically' if sev == 'critical' else '')} overloaded — {int(loading * 100)}% of {cap:g} kW nameplate", 'evidence': {'load_kw': round(d['act'], 2), 'capacity_kw': cap, 'loading_pct': round(loading * 100, 1), 'feeder': d['feeder']}})
    if spec_meta:
        feeder_meters: dict[str, set] = {}
        for mid_, m in spec_meta.items():
            feeder_meters.setdefault(m['feeder'], set()).add(mid_)
        silent = {}
        for r in snapshot:
            silent.setdefault(r['feeder'], set())
        for feeder, mids in feeder_meters.items():
            missing = {m for m in mids if m not in seen}
            ratio = len(missing) / len(mids) if mids else 0
            if ratio >= OUTAGE_RATIO:
                alerts.append({'key': f'outage:{feeder}:{bucket}', 'kind': 'feeder_outage', 'severity': 'critical', 'meter_id': None, 'scope': feeder, 'title': f'Feeder outage — {feeder}: {len(missing)}/{len(mids)} meters silent', 'evidence': {'feeder': feeder, 'silent_meters': sorted(missing), 'silent_pct': round(ratio * 100, 1)}})
    return alerts
RISK_WEIGHTS = {'critical': 45, 'warning': 18}
KIND_WEIGHTS = {'bypass': 15, 'tamper': 15, 'neutral_tamper': 12, 'feeder_outage': 12, 'tx_loss': 10, 'overload': 8, 'frequency': 6}

def meter_risk(alerts: list[dict], meter_id: str) -> dict:
    score = 0
    reasons = []
    for a in alerts:
        if a.get('meter_id') != meter_id:
            continue
        score += RISK_WEIGHTS.get(a['severity'], 10) + KIND_WEIGHTS.get(a['kind'], 0)
        reasons.append(a['kind'])
    return {'score': min(100, score), 'reasons': sorted(set(reasons))}

def fleet_health(per_meter_risk: dict[str, dict], total_meters: int) -> int:
    if total_meters <= 0:
        return 100
    penalty = sum((r['score'] for r in per_meter_risk.values())) / total_meters
    return max(0, round(100 - penalty))

def recommended_action(kind: str, ev: dict) -> str:
    if kind == 'bypass':
        return f"Dispatch a field team to inspect the meter seal and service line for a direct hook. Baseline was {ev.get('kw_baseline')} kW and the meter now reports {ev.get('kw_now')} kW at {ev.get('voltage')} V — a healthy installation does not drop like that while voltage holds."
    if kind == 'tamper':
        return 'Send an inspection crew today: reverse-flow events with the cover-open flag usually mean the meter has been opened or an export clamp is fitted. Photograph the seal before touching.'
    if kind in ('undervoltage', 'overvoltage'):
        return 'Log a distribution-fault ticket: sustained voltage outside 195–253 V damages customer equipment. Check the transformer tap and neutral on that feeder.'
    if kind == 'imbalance':
        return 'Rebalance single-phase customers across L1/L2/L3 at the distribution board — the spread pays back as lower neutral losses and fewer tripped breakers.'
    if kind == 'offline':
        return 'Ping the meter over the AMI network; if it stays silent, schedule a SIM/antenna check — an unmonitored meter is an unguarded meter.'
    if kind == 'tx_loss':
        return f"Walk the {ev.get('feeder', '')} feeder at night with a clamp meter: losses of {ev.get('loss_pct')}% on one transformer usually mean illegal connections upstream of meters."
    if kind == 'neutral_tamper':
        return 'Immediate safety inspection: a displaced or deliberately lifted neutral pushes dangerous overvoltages onto one phase while another sags. Isolate the service, test earth continuity and re-terminate the neutral before re-energising.'
    if kind == 'frequency':
        return 'This is a system-balancing event, not customer theft: log it with control and check whether under-frequency load shedding should step in before generation trips.'
    if kind == 'overload':
        return f"Load-shed non-essential customers on {ev.get('feeder', '')} or re-tie the feeder: {ev.get('loading_pct')}% of nameplate risks transformer overheating and protection trips."
    if kind == 'low_pf':
        return 'Reactive power this high points to an inductive shunt or uncorrected motor load. Inspect the service for a tapped coil/ballast; a PF correction capacitor bank clears the overload.'
    if kind == 'feeder_outage':
        return f"Treat as a confirmed outage: {ev.get('silent_pct')}% of {ev.get('feeder')} meters are dark. Dispatch a fault patrol to the feeder head/recloser and prepare an SMS advisory for the area."
    return 'Review the evidence and schedule an inspection.'


def risk_from_open(open_alerts: list[dict], all_meters: list[str]):
    per = {m: {"score": 0, "reasons": set()} for m in all_meters}
    group_penalty = 0
    for a in open_alerts:
        w = RISK_WEIGHTS.get(a.get("severity"), 10) + KIND_WEIGHTS.get(a.get("kind"), 0)
        mid = a.get("meter_id")
        if mid and mid in per:
            per[mid]["score"] += w
            per[mid]["reasons"].add(a.get("kind", "alert"))
        else:
            group_penalty += w
    risks = {m: {"score": min(100, v["score"]), "reasons": sorted(v["reasons"])} for m, v in per.items()}
    meter_avg = (sum(r["score"] for r in risks.values()) / len(all_meters)) if all_meters else 0
    health = max(0, round(100 - meter_avg - min(35, group_penalty)))
    return risks, health
