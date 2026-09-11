import React, { useEffect, useMemo, useRef, useState } from "react";
import { getLive, getNetwork, getMeter, getDevices, postScenario, ackAlert, resolveAlert, investigate } from "./api.js";

/* ---------------- hooks ---------------- */
function useLive() {
  const [data, setData] = useState(null);
  const hist = useRef([]);
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const d = await getLive();
        if (stop) return;
        hist.current = [...hist.current, { t: d.now, kw: d.kpis.delivered_kw }].slice(-48);
        setData(d);
      } catch {}
    };
    tick();
    const iv = setInterval(tick, 4000);
    return () => { stop = true; clearInterval(iv); };
  }, []);
  return { data, hist: hist.current };
}

/* ---------------- small pieces ---------------- */
const KwBar = ({ kw, base }) => {
  const ratio = base > 0 ? kw / base : 0;
  const w = Math.max(3, Math.min(100, ratio * 100));
  const cls = ratio < 0.45 ? "low" : ratio < 0.75 ? "mid" : "";
  return (
    <div className="bar" title={`${kw} kW vs baseline ${base} kW`}>
      <i className={cls} style={{ width: `${w}%` }} />
    </div>
  );
};

const Spark = ({ hist }) => {
  if (!hist.length) return null;
  const w = 560, h = 74;
  const kws = hist.map((p) => p.kw);
  const min = Math.min(...kws) * 0.96, max = Math.max(...kws) * 1.04;
  const pts = hist.map((p, i) =>
    `${(i / Math.max(1, hist.length - 1)) * w},${h - ((p.kw - min) / (max - min || 1)) * (h - 8) - 4}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(47,213,117,0.35)" />
          <stop offset="100%" stopColor="rgba(47,213,117,0)" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill="url(#sg)" />
      <polyline points={pts} fill="none" stroke="#2fd575" strokeWidth="1.6" />
    </svg>
  );
};

/* ---------------- network schematic ---------------- */
function NetworkMap({ meters, alerts, onPick }) {
  if (!meters) return null;
  const byId = Object.fromEntries(meters.map((m) => [m.meter_id, m]));
  const alertIds = new Set((alerts || []).filter((a) => a.severity === "critical" && a.meter_id).map((a) => a.meter_id));
  const feeders = [
    { name: "FEEDER-A", spine: 70, tx: [{ id: "TX-A1", y: 118 }, { id: "TX-A2", y: 268 }], row: [150, 300], x0: 120 },
    { name: "FEEDER-B", spine: 70, tx: [{ id: "TX-B1", y: 418 }], row: [450], x0: 160 },
  ];
  const mstatus = (id) => {
    const m = byId[id];
    if (!m) return "off";
    if (alertIds.has(id)) return "fault";
    return m.status === "fault" ? "fault" : "ok";
  };
  const col = (s) => (s === "fault" ? "#ff4d5e" : s === "ok" ? "#2fd575" : "#3d5063");
  return (
    <svg className="schem" viewBox="0 0 900 520">
      <text className="feeder-l" x="34" y="84">FEEDER-A</text>
      <line className="trunk" x1="70" y1="78" x2="520" y2="78" />
      <line className="flow" x1="70" y1="78" x2="520" y2="78" />
      <text className="feeder-l" x="34" y="424">FEEDER-B</text>
      <line className="trunk" x1="70" y1="418" x2="820" y2="418" />
      <line className="flow" x1="70" y1="418" x2="820" y2="418" />
      {feeders.map((f) =>
        f.tx.map((t) => {
          const metersTx = meters.filter((m) => m.transformer === t.id);
          const yTo = Math.min(...metersTx.map((m) => m.y), f.row[0]) - 18;
          return (
            <g key={t.id}>
              <line className="trunk" x1={t.id === "TX-A1" ? 300 : t.id === "TX-A2" ? 300 : 300} y1={t.y + 14} x2={300} y2={t.y + 14 + 22} />
              <rect className="tx" x="278" y={t.y} width="44" height="26" rx="4" />
              <text className="txlabel" x="286" y={t.y + 17}>{t.id}</text>
            </g>
          );
        })
      )}
      {meters.map((m) => {
        const s = mstatus(m.meter_id);
        return (
          <g key={m.meter_id} onClick={() => onPick(m.meter_id)}>
            <line x1={m.x} y1={m.y - 22} x2={m.x} y2={m.y - 8} stroke="#22344a" strokeWidth="1.5" />
            <circle
              className="meter-c"
              cx={m.x} cy={m.y} r={s === "fault" ? 8 : 6.5}
              fill={s === "fault" ? "rgba(255,77,94,0.25)" : "rgba(47,213,117,0.12)"}
              stroke={col(s)}
            >
              {s === "fault" && <animate attributeName="r" values="7;9.5;7" dur="1.1s" repeatCount="indefinite" />}
            </circle>
            <text className="meter-l" x={m.x - 16} y={m.y + 22}>{m.meter_id}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ---------------- overview ---------------- */
function Overview({ data, hist, onPick }) {
  if (!data) return <div className="subt">Connecting to telemetry…</div>;
  const k = data.kpis;
  return (
    <div>
      <div className="kpis">
        <div className="kpi kpi--cyan">
          <div className="kpi__label">Delivered now</div>
          <div className="kpi__value">{k.delivered_kw.toFixed(2)} <small>kW</small></div>
          <div className="kpi__foot">expected {k.expected_kw.toFixed(2)} kW on this interval</div>
        </div>
        <div className="kpi kpi--warn">
          <div className="kpi__label">Network loss</div>
          <div className="kpi__value">{k.loss_pct.toFixed(1)}<small>%</small></div>
          <div className="kpi__foot">delivered vs expected, live</div>
        </div>
        <div className="kpi kpi--ok">
          <div className="kpi__label">Meters online</div>
          <div className="kpi__value">{k.online}<small>/{k.total}</small></div>
          <div className="kpi__foot">poll cycle every 4 s</div>
        </div>
        <div className={`kpi ${k.critical ? "kpi--crit" : ""}`}>
          <div className="kpi__label">Critical alerts</div>
          <div className="kpi__value">{k.critical}</div>
          <div className="kpi__foot">{k.alerts_open} open incidents total</div>
        </div>
      </div>
      <div className="grid-2">
        <div className="panel">
          <div className="panel__head">Network schematic — 3 feeders · 4 transformers · 18 meters <span className="fill" /> <span className="mono st-ok">● live</span></div>
          <div style={{ padding: "8px 10px" }}>
            <NetworkMap meters={data.meters} alerts={data.alerts} onPick={onPick} />
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="panel">
            <div className="panel__head">Feeder load — last {hist.length || 0} ticks</div>
            <div style={{ padding: "6px 10px 4px" }}><Spark hist={hist} /></div>
          </div>
          <div className="panel" style={{ flex: 1 }}>
            <div className="panel__head">Alert ticker</div>
            <div className="ticker" style={{ padding: "10px 14px" }}>
              {(data.alerts || []).slice(0, 9).map((a) => (
                <div className="tk" key={a.id}>
                  <span className={`al__sev sev-${a.severity}`}>{a.severity}</span>
                  <b>{a.title}</b>
                  <span className="t">{(a.created_at || "").slice(11, 19)}</span>
                </div>
              ))}
              {!data.alerts.length && <div className="tk"><b>Board is quiet — no open incidents.</b></div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------- meters ---------------- */
function MetersView({ data, picked, setPicked }) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    if (picked) getMeter(picked).then(setDetail).catch(() => {});
  }, [picked]);
  const d = data?.meters || [];
  const sel = d.find((m) => m.meter_id === picked);
  const maxKw = Math.max(...d.map((m) => m.kw), 0.001);
  return (
    <div className="grid-2" style={{ gridTemplateColumns: "1fr 360px" }}>
      <div className="panel">
        <div className="panel__head">Meter fleet — live readings</div>
        <table>
          <thead><tr><th>ID</th><th>Customer / asset</th><th>Transformer</th><th>Load vs baseline</th><th>kW</th><th>V</th><th>Status</th></tr></thead>
          <tbody>
            {d.map((m) => (
              <tr key={m.meter_id} className="rowlink" onClick={() => setPicked(m.meter_id)}>
                <td className="mono">{m.meter_id}</td>
                <td>{m.name}</td>
                <td className="mono" style={{ color: "var(--muted)" }}>{m.transformer}</td>
                <td><KwBar kw={m.kw} base={m.baseline_kw} /></td>
                <td>{m.kw.toFixed(2)}</td>
                <td style={{ color: m.voltage < 195 || m.voltage > 253 ? "var(--crit)" : "var(--muted)" }}>{m.voltage.toFixed(0)}</td>
                <td className={`mono st-${m.status}`}>{m.status === "ok" ? "● ok" : "● fault"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ alignSelf: "start", position: "sticky", top: 0 }}>
        <div className="panel__head">{picked ? `Meter ${picked}` : "Meter detail"}</div>
        <div style={{ padding: "12px 14px" }}>
          {sel ? (
            <>
              <div style={{ fontWeight: 700, marginBottom: 2 }}>{sel.name}</div>
              <div className="subt mono">{sel.feeder} · {sel.transformer} · {sel.kind}</div>
              <div style={{ display: "flex", gap: 16, margin: "10px 0" }}>
                <div><div className="kpi__label">Power</div><div className="kpi__value" style={{ fontSize: 20 }}>{sel.kw.toFixed(3)} <small>kW</small></div></div>
                <div><div className="kpi__label">Baseline</div><div className="kpi__value" style={{ fontSize: 20, color: "var(--muted)" }}>{sel.baseline_kw.toFixed(3)} <small>kW</small></div></div>
                <div><div className="kpi__label">Voltage</div><div className="kpi__value" style={{ fontSize: 20 }}>{sel.voltage.toFixed(1)} <small>V</small></div></div>
              </div>
              <div className="kpi__label" style={{ marginBottom: 6 }}>Phase currents L1/L2/L3</div>
              <div className="al__ev" style={{ marginBottom: 14 }}>
                {sel.phase_current.map((c, i) => <span key={i} className="ev">L{i + 1} <b>{c.toFixed(2)} A</b></span>)}
                {sel.reverse_events > 0 && <span className="ev" style={{ color: "var(--warn)" }}>reverse events <b>{sel.reverse_events}</b></span>}
                {sel.flags?.cover_open && <span className="ev" style={{ color: "var(--crit)" }}>COVER OPEN</span>}
              </div>
              {detail && (
                <>
                  <div className="kpi__label" style={{ marginBottom: 6 }}>24 h profile</div>
                  <svg viewBox="0 0 560 120" style={{ width: "100%" }}>
                    {(() => {
                      const mx = Math.max(...detail.history.map((h) => h.kw));
                      return detail.history.map((h, i) => {
                        const bh = (h.kw / mx) * 100;
                        return <rect key={i} x={(i / 24) * 560 + 3} y={110 - bh} width="16" height={bh} fill={h.kw < mx * 0.3 ? "#ff4d5e" : "rgba(47,213,117,0.6)"} rx="2" />;
                      });
                    })()}
                  </svg>
                  <div className="subt" style={{ marginTop: 4 }}>red bars = hours the engine would flag</div>
                </>
              )}
            </>
          ) : <div className="subt">Select a meter from the table — or click a node on the schematic.</div>}
        </div>
      </div>
    </div>
  );
}

/* ---------------- alerts ---------------- */
function AlertsView({ data, reload }) {
  const [reports, setReports] = useState({});
  const [busy, setBusy] = useState(0);
  const alerts = data?.alerts || [];
  const gen = async (id) => {
    setBusy(id);
    try {
      const r = await investigate(id);
      setReports((p) => ({ ...p, [id]: r }));
    } finally { setBusy(0); }
  };
  return (
    <div style={{ maxWidth: 860 }}>
      {alerts.map((a) => (
        <div className="al" key={a.id}>
          <div className="al__top">
            <span className={`al__sev sev-${a.severity}`}>{a.severity}</span>
            <span className="al__kind mono">{a.kind} · {a.meter_id || a.scope}</span>
            <span className="al__kind mono" style={{ marginLeft: "auto" }}>{a.status}</span>
          </div>
          <div className="al__title">{a.title}</div>
          <div className="al__ev">
            {Object.entries(a.evidence || {}).slice(0, 7).map(([k, v]) => (
              <span className="ev" key={k}>{k} <b>{String(v)}</b></span>
            ))}
          </div>
          {reports[a.id] && (
            <div>
              <div className="report__prov">investigator · {reports[a.id].provider}</div>
              <div className="report">{reports[a.id].report}</div>
            </div>
          )}
          <div className="al__actions">
            <button className="btn btn--primary" disabled={busy === a.id} onClick={() => gen(a.id)}>
              {reports[a.id] ? "Regenerate report" : "Generate investigator report"}
            </button>
            {a.status === "open" && <button className="btn" onClick={() => ackAlert(a.id).then(reload)}>Acknowledge</button>}
            {a.status !== "resolved" && <button className="btn" onClick={() => resolveAlert(a.id).then(reload)}>Resolve</button>}
          </div>
        </div>
      ))}
      {!alerts.length && (
        <div className="panel" style={{ padding: 20 }}><div className="subt">No open incidents. Arm a field-test scenario (bottom right) and watch the engine catch it live.</div></div>
      )}
    </div>
  );
}

/* ---------------- devices / api ---------------- */
const esp32 = `#include <WiFi.h>          // + EmonLib for rms current
#include <HTTPClient.h>

// measure: emon1.current(A0, 30.0); float amps = emon1.calcIrms(1480);
float volts = 228.4, kw = volts * amps * pf / 1000.0;

HTTPClient http;
http.begin("https://gridsentry.onrender.com/api/ingest/M-101");
http.addHeader("Authorization", "Bearer gs_...device-token...");
http.addHeader("Content-Type", "application/json");
http.POST("{\"voltage\":" + String(volts) + ",\"kw\":" + String(kw) + "}");
// repeat every 15 s; the engine raises alerts server-side`;

function DevicesView() {
  const [devs, setDevs] = useState([]);
  useEffect(() => { getDevices().then((d) => setDevs(d.devices)).catch(() => {}); }, []);
  const ex = devs[1];
  return (
    <div style={{ maxWidth: 900 }}>
      <div className="section-t">Any meter can join the grid — one POST</div>
      <div className="subt">
        GridSentry ships with 18 virtual meters for the demo, but the ingestion path is real: any ESP32 +
        CT-clamp (or an existing AMI head-end) can stream readings to one endpoint. The engine treats device
        telemetry exactly like simulated telemetry — same rules, same alerts.
      </div>
      <div className="code">{`POST /api/ingest/M-101
Authorization: Bearer <device-token>
Content-Type: application/json

{
  `}<span className="s">"voltage"</span>{`: 228.4, `}<span className="s">"current"</span>{`: 4.2, `}<span className="s">"kw"</span>{`: 0.62,
  `}<span className="s">"reverse_events"</span>{`: 0,
  `}<span className="s">"phases"</span>{`: [229.1, 228.7, 228.9],
  `}<span className="s">"phase_current"</span>{`: [1.5, 1.4, 1.3],
  `}<span className="s">"cover_open"</span>{`: false
}`}</div>
      {ex && (
        <div style={{ margin: "10px 0 18px" }}>
          <span className="tok">example token for {ex.meter_id}: {ex.token}</span>
        </div>
      )}
      <div className="section-t">Reference node — ESP32 + SCT-013 clamp (the lines that matter)</div>
      <div className="code">{esp32}</div>
      <div className="section-t">Device registry (demo fleet)</div>
      <div className="panel">
        <table>
          <thead><tr><th>Meter</th><th>Asset</th><th>Feeder</th><th>Device token</th></tr></thead>
          <tbody>
            {devs.map((d) => (
              <tr key={d.meter_id}>
                <td className="mono">{d.meter_id}</td>
                <td>{d.name}</td>
                <td className="mono" style={{ color: "var(--muted)" }}>{d.feeder}</td>
                <td className="mono" style={{ color: "var(--dim)", fontSize: 11 }}>{d.token}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------- scenario bar ---------------- */
function ScenarioBar({ onFire }) {
  const fire = (kind, meter_id, feeder) => postScenario(kind, meter_id, feeder).then(onFire);
  return (
    <div className="scen">
      <div className="scen__label">Field test — arm a scenario</div>
      <div className="scen__row">
        <button className="scen__btn" onClick={() => fire("bypass", "M-102")}>⚡ Bypass M-102</button>
        <button className="scen__btn" onClick={() => fire("sag", null, "FEEDER-A")}>📉 Sag FEEDER-A</button>
        <button className="scen__btn" onClick={() => fire("imbalance", "M-103")}>∽ Imbalance M-103</button>
        <button className="scen__btn" onClick={() => fire("tamper", "M-110")}>🔓 Tamper M-110</button>
        <button className="scen__btn" onClick={() => fire("offline", "M-108")}>📴 Offline M-108</button>
      </div>
    </div>
  );
}

/* ---------------- shell ---------------- */
export default function App() {
  const { data, hist } = useLive();
  const [view, setView] = useState("overview");
  const [picked, setPicked] = useState(null);
  const [toast, setToast] = useState(null);
  const reload = () => getLive().then(() => {});
  const fire = () => {
    setToast("Scenario armed — engine is watching the board…");
    setTimeout(() => setToast(null), 3200);
  };
  const crit = data?.kpis.critical || 0;
  const nav = [
    { id: "overview", label: "Overview", ic: "▦" },
    { id: "meters", label: "Meters", ic: "◍" },
    { id: "alerts", label: "Alerts", ic: "⚠", badge: crit },
    { id: "devices", label: "Devices & API", ic: "⌁" },
  ];
  const clock = data ? data.now.slice(11, 19) + " UTC" : "--:--:--";
  return (
    <div className="app">
      <aside className="side">
        <div className="side__logo">
          <div className="side__bolt">⚡</div>
          <div>
            <div className="side__name">Grid<span>Sentry</span></div>
            <div className="side__sub">grid operations</div>
          </div>
        </div>
        {nav.map((n) => (
          <button key={n.id} className={`side__item ${view === n.id ? "on" : ""}`} onClick={() => setView(n.id)}>
            <span className="ic">{n.ic}</span> {n.label}
            {!!n.badge && <span className="side__badge">{n.badge}</span>}
          </button>
        ))}
        <div className="side__foot">
          VoltHacks 2026<br />Sustainability &amp; Smart Cities<br />demo fleet · 18 virtual meters
        </div>
      </aside>
      <div className="main">
        <header className="top">
          <span className="live"><span className="dot" />TELEMETRY LIVE</span>
          <span className="clock mono">{clock}</span>
          <span className="fill" />
          {data && (
            <span className="losspill">network loss <b>{data.kpis.loss_pct.toFixed(1)}%</b></span>
          )}
        </header>
        <main className="content">
          {view === "overview" && <Overview data={data} hist={hist} onPick={(id) => { setPicked(id); setView("meters"); }} />}
          {view === "meters" && <MetersView data={data} picked={picked} setPicked={setPicked} />}
          {view === "alerts" && <AlertsView data={data} reload={reload} />}
          {view === "devices" && <DevicesView />}
        </main>
      </div>
      <ScenarioBar onFire={fire} />
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
