"""Investigator reports: deterministic offline provider (always available),
optional OpenAI-compatible LLM (Groq) refinement when configured."""
import json
import os
import httpx
from .engine import recommended_action


def build_offline_report(alert, reading: dict | None) -> dict:
    ev = {}
    try:
        ev = json.loads(alert.evidence or "{}")
    except Exception:
        ev = {}
    what = alert.title
    lines = [f"What happened: {what}."]
    if reading:
        lines.append(
            f"Current telemetry: {reading['kw']} kW at {reading['voltage']} V "
            f"(baseline {reading.get('baseline_kw')} kW) on {reading['transformer']}."
        )
    if ev:
        lines.append("Evidence on file: " + ", ".join(f"{k}={v}" for k, v in list(ev.items())[:6]) + ".")
    action = recommended_action(alert.kind, ev)
    lines.append(f"Recommended action: {action}")
    lines.append("Reports cite only the numbers in the evidence record — estimates are not silently invented.")
    return {"provider": "offline", "alert_id": alert.id, "report": "\n\n".join(lines),
            "action": action, "confidence": "high" if alert.severity == "critical" else "medium"}


def refine_with_llm(alert, reading: dict | None) -> dict | None:
    base = os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1")
    key = os.environ.get("AI_API_KEY")
    if not key:
        return None
    model = os.environ.get("AI_MODEL", "openai/gpt-oss-20b")
    offline = build_offline_report(alert, reading)
    try:
        r = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": (
                        "You are a grid-operations investigator. Using ONLY the facts in the draft report, "
                        "rewrite it as a concise incident brief for a field supervisor: What happened / "
                        "Evidence / Likely cause / Field action. No new numbers. Max 160 words. Plain text.")},
                    {"role": "user", "content": offline["report"]},
                ],
                "temperature": 0.2,
                "max_tokens": 900,
            },
            timeout=8,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return {"provider": f"llm:{model}", "alert_id": alert.id, "report": text,
                "action": offline["action"], "confidence": offline["confidence"]}
    except Exception:
        return None


def investigate(alert, reading: dict | None) -> dict:
    mode = os.environ.get("AI_MODE", "auto")
    if mode in ("auto", "remote"):
        out = refine_with_llm(alert, reading)
        if out:
            return out
    return build_offline_report(alert, reading)
