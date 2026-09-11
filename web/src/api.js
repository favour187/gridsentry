const J = (r) => { if (!r.ok) throw new Error(r.status); return r.json(); };
export const getLive = () => fetch("/api/live").then(J);
export const getStats = () => fetch("/api/stats").then(J);
export const getNetwork = () => fetch("/api/network").then(J);
export const getMeter = (id) => fetch(`/api/meters/${id}`).then(J);
export const getDevices = () => fetch("/api/devices").then(J);
export const csvUrl = "/api/incidents.csv";
export const postScenario = (kind, meter_id, feeder) =>
  fetch("/api/scenarios", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, meter_id, feeder }) }).then(J);
export const ackAlert = (id) => fetch(`/api/alerts/${id}/ack`, { method: "POST" }).then(J);
export const resolveAlert = (id) => fetch(`/api/alerts/${id}/resolve`, { method: "POST" }).then(J);
export const investigate = (id) => fetch(`/api/investigate/${id}`, { method: "POST" }).then(J);
