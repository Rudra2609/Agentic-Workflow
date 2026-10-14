#!/usr/bin/env python3
"""Writes ``dashboards/hmap.json`` (the committed Grafana dashboard, Sprint 4 item 4.17). Edit the panel list here and
re-run ``python3 infra/observability/grafana/build_dashboard.py``; the JSON is what Grafana provisions."""

import json
from pathlib import Path

PROM = {"type": "prometheus", "uid": "hmap-prom"}
_id = iter(range(1, 1000))


def panel(title: str, exprs: list[tuple[str, str]], *, x: int, y: int, w: int = 12, h: int = 8,
          kind: str = "timeseries", unit: str = "short", description: str = "", stack: bool = False,
          thresholds: list[tuple[str, float | None]] | None = None) -> dict:
    steps = [{"color": c, "value": v} for c, v in (thresholds or [("green", None)])]
    p = {"id": next(_id), "type": kind, "title": title, "description": description, "datasource": PROM,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [{"refId": chr(65 + i), "datasource": PROM, "expr": e, "legendFormat": legend,
                      "instant": kind in ("stat", "table"), "range": kind not in ("stat", "table"),
                      **({"format": "table"} if kind == "table" else {})}
                     for i, (e, legend) in enumerate(exprs)],
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps},
                                      "custom": {"stacking": {"mode": "normal" if stack else "none"},
                                                 "fillOpacity": 10}}, "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                     "tooltip": {"mode": "multi", "sort": "desc"}}}
    if kind == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background", "graphMode": "none", "textMode": "value_and_name"}
    if kind == "table":
        p["options"] = {"showHeader": True}
        p["transformations"] = [{"id": "organize", "options": {"excludeByName": {"Time": True, "Value": True,
                                                                                 "__name__": True}}}]
    return p


def row(title: str, y: int) -> dict:
    return {"id": next(_id), "type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24,
                                                                                          "h": 1}, "panels": []}


RED = [("green", None), ("red", 1)]
panels = [
    row("Is anything wrong right now?", 0),
    panel("Firing alerts", [('count(ALERTS{alertstate="firing"}) or vector(0)', "firing")], x=0, y=1, w=4, h=4,
          kind="stat", thresholds=RED, description="Alert rules: infra/observability/prometheus/alerts.yml"),
    panel("Dead-lettered tasks", [("max(hmap_dead_lettered_tasks) or vector(0)", "waiting for an operator")], x=4,
          y=1, w=5, h=4, kind="stat", thresholds=RED, description="Replay them from the Ops page (a new attempt)."),
    panel("Bus dead letters", [("max(hmap_bus_dlq_messages) or vector(0)", "hmap.dlq")], x=9, y=1, w=5, h=4,
          kind="stat", thresholds=RED),
    panel("Agents", [("sum by (state) (hmap_agents)", "{{state}}")], x=14, y=1, w=5, h=4, kind="stat"),
    panel("RAM available", [("min(hmap_system_memory_available_bytes)", "free")], x=19, y=1, w=5, h=4,
          kind="stat", unit="bytes", thresholds=[("red", None), ("orange", 1.5e9), ("green", 3e9)]),
    panel("Firing alerts (details)", [('ALERTS{alertstate="firing"}', "{{alertname}}")], x=0, y=5, w=24, h=5,
          kind="table"),
    row("Queues and tasks", 10),
    panel("Queue depth", [('sum by (queue) (hmap_queue_depth{queue!~"hmap.events.tmp.*"})', "{{queue}}")], x=0, y=11,
          description="Messages waiting in each bus queue (from bus.queue_depths)."),
    panel("Oldest READY task (queue age)", [("max by (capability) (hmap_queue_oldest_ready_seconds) or vector(0)",
                                             "{{capability}}")], x=12, y=11, unit="s",
          description="How long the oldest ready task of each capability has waited for an agent."),
    panel("Task state changes / s", [("sum by (state) (rate(hmap_task_transitions_total[1m]))", "{{state}}")],
          x=0, y=19, stack=True),
    panel("Retries, dead letters, replays (per minute)",
          [("sum(rate(hmap_task_retries_total[1m])) * 60", "retries"),
           ("sum(rate(hmap_task_dead_letters_total[1m])) * 60", "dead letters"),
           ("sum(rate(hmap_task_replays_total[1m])) * 60", "replays"),
           ("sum by (consumer) (rate(hmap_dedup_hits_total[1m])) * 60", "dedup hits {{consumer}}")], x=12, y=19),
    panel("Live tasks by state", [("sum by (state) (hmap_tasks)", "{{state}}")], x=0, y=27, stack=True),
    panel("Agent heartbeat age", [("max by (agent_id) (hmap_agent_heartbeat_age_seconds)", "{{agent_id}}")], x=12,
          y=27, unit="s", thresholds=[("green", None), ("red", 30)],
          description="Above 30 s the agent's lease expires and its work is retried elsewhere."),
    row("Agents and models", 35),
    panel("Agent handler time (p95)", [("histogram_quantile(0.95, sum by (le, capability) "
                                        "(rate(hmap_agent_handle_seconds_bucket[5m])))", "{{capability}}")], x=0,
          y=36, unit="s"),
    panel("Model latency p50 / p95 by role",
          [("histogram_quantile(0.5, sum by (le, role) (rate(hmap_llm_latency_seconds_bucket[5m])))", "p50 {{role}}"),
           ("histogram_quantile(0.95, sum by (le, role) (rate(hmap_llm_latency_seconds_bucket[5m])))",
            "p95 {{role}}")], x=12, y=36, unit="s"),
    panel("Model tokens / min", [("sum by (role, provider, direction) (rate(hmap_llm_tokens_total[1m])) * 60",
                                  "{{role}} {{provider}} {{direction}}")], x=0, y=44),
    panel("Model calls / min by outcome", [("sum by (provider, outcome) (rate(hmap_llm_calls_total[1m])) * 60",
                                            "{{provider}} {{outcome}}")], x=12, y=44),
    row("Refinement (Member 4)", 52),
    panel("Refinement loops by stop reason", [("sum by (capability, stop_reason) (hmap_refine_runs_total)",
                                               "{{capability}} {{stop_reason}}")], x=0, y=53, w=12),
    panel("Mean score gain per loop", [("sum by (capability) (rate(hmap_refine_score_gain_sum[30m])) / "
                                        "clamp_min(sum by (capability) (rate(hmap_refine_score_gain_count[30m])), "
                                        "1e-9)", "{{capability}}")], x=12, y=53, w=12),
    row("Memory", 61),
    panel("Process memory (RSS)", [("max by (process) (hmap_process_rss_bytes)", "{{process}}")], x=0, y=62,
          unit="bytes"),
    panel("RAM available on this computer", [("min(hmap_system_memory_available_bytes)", "available"),
                                             ("max(hmap_system_memory_total_bytes)", "total")], x=12, y=62,
          unit="bytes"),
]

dashboard = {
    "uid": "hmap-overview", "title": "hmap — platform overview", "tags": ["hmap", "sprint-4"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "editable": False, "refresh": "5s", "time": {"from": "now-30m", "to": "now"},
    "links": [{"title": "Jaeger traces", "type": "link", "url": "http://127.0.0.1:16686", "targetBlank": True},
              {"title": "Prometheus alerts", "type": "link", "url": "http://127.0.0.1:9090/alerts",
               "targetBlank": True}],
    "annotations": {"list": []}, "templating": {"list": []}, "panels": panels,
}

out = Path(__file__).resolve().parent / "dashboards" / "hmap.json"
out.write_text(json.dumps(dashboard, indent=1) + "\n")
print(f"wrote {out} ({len(panels)} panels)")
