""""Why did this task fail?" (Sprint 4 item 4.16; Member 1's research §11): one answer built from everything the
platform already records, in the order a person would check it:

    final state -> last error -> executions (attempts, agents, timeouts, superseded) -> messages (assignments sent,
    processed once per inbox, late / duplicate reports kept as evidence) -> trace (Jaeger link) -> artifacts

The verdict is a plain sentence plus a few facts and what the operator can do (replay a dead letter as a new
attempt, replan, run again). Nothing here changes state.
"""

from collections import Counter
from typing import Any

from hmap.agents.ops.history import task_events, task_messages
from hmap.obs import task_trace_id, trace_id_of

ERROR_WORDS: dict[str, str] = {
    "TOOL_TRANSIENT": "a temporary tool or network error",
    "MODEL_TRANSIENT": "the model was temporarily unavailable",
    "TIMEOUT": "it took too long (timeout)",
    "AGENT_UNAVAILABLE": "the agent went away (crashed, stopped or lost its connection)",
    "RATE_LIMITED": "a rate limit",
    "INVALID_TASK": "the task itself was invalid (missing or wrong input)",
    "INVALID_MESSAGE": "a malformed message",
    "MISSING_CONTEXT": "information it needs is missing",
    "DEPENDENCY": "a step it depends on did not finish",
    "WRONG_RESULT": "the agent reported that its result is wrong",
    "CANCELLED": "it was cancelled",
    "INTERNAL_AGENT": "an error inside the agent",
}


def _error_text(err: dict[str, Any] | None) -> str:
    if not err:
        return "an unknown error"
    code = str(err.get("code") or "")
    words = ERROR_WORDS.get(code, code.replace("_", " ").lower() or "an error")
    msg = str(err.get("message") or "").strip()
    return f"{words} ({code}: {msg[:160]})" if msg and code else words


def _summarise_event(e: dict[str, Any]) -> str:
    data = e.get("data") or {}
    t = e.get("event_type", "")
    if t == "task.assigned":
        return f"assigned to {data.get('agent_id')} (attempt {data.get('attempt')})"
    if t in ("task.accepted", "task.started"):
        return f"{t.split('.')[1]} by {data.get('agent_id')}"
    if t == "task.retrying":
        err = data.get("error") or {}
        return f"attempt {err.get('attempt')} failed ({err.get('code')}); retry {data.get('retry')} in " \
               f"{float(data.get('delay_s') or 0):.1f} s"
    if t in ("task.failed", "task.dead_lettered", "task.blocked"):
        return f"{t.split('.')[1].replace('_', ' ')}: {(data.get('error') or {}).get('code') or data.get('reason')}"
    if t == "task.cancelled":
        return f"cancelled: {data.get('reason')}"
    if t == "task.replayed":
        return f"replayed by {data.get('by')}: {data.get('reason')}"
    if t == "task.ready":
        return f"ready ({data.get('reason') or 'dependencies complete'})"
    if t == "task.completed":
        return f"completed: {data.get('summary') or ''}".strip()
    if t.startswith("refine."):
        return f"{t}: score {data.get('score')}"
    return str(t)


def verdict(task: dict[str, Any], executions: list[dict[str, Any]], deps: list[dict[str, Any]],
            dependants: list[dict[str, Any]]) -> dict[str, Any]:
    state = task["state"]
    attempts = len(executions)
    facts: list[str] = []
    codes = Counter(str((e.get("error") or {}).get("code")) for e in executions if e.get("error")
                    and (e.get("error") or {}).get("code") != "REJECTED")
    offline = [e for e in executions if e.get("orphaned_at") or (e.get("error") or {}).get("code") ==
               "AGENT_UNAVAILABLE"]
    late = sum(len(e.get("evidence") or []) for e in executions)
    if codes:
        facts.append("errors: " + ", ".join(f"{c} x{n}" for c, n in codes.most_common()))
    if offline:
        facts.append(f"{len(offline)} attempt(s) lost their agent (it stopped sending heartbeats or went offline); "
                     "the Manager retried on another attempt")
    if late:
        facts.append(f"{late} late or duplicate report(s) arrived after their attempt had ended; they were kept as "
                     "evidence and changed nothing")
    if task.get("replays"):
        facts.append(f"replayed {task['replays']} time(s) by an operator")
    err = task.get("last_error")
    blocked_dependants = [d["task_id"] for d in dependants if d["state"] == "BLOCKED"]
    if blocked_dependants:
        facts.append(f"{len(blocked_dependants)} step(s) that wait for it are blocked")
    if state == "COMPLETED":
        headline = f"It did not fail: it finished on attempt {attempts}." if attempts else "It finished."
        status = "completed"
        if attempts > 1:
            headline = f"It finished on attempt {attempts}, after {attempts - 1} failed or lost attempt(s)."
    elif state == "DEAD_LETTERED":
        status = "dead_lettered"
        headline = (f"It gave up after {attempts} attempt(s): {_error_text(err)}. Temporary errors are retried "
                    "automatically; this one kept happening, so it waits for an operator.")
    elif state == "FAILED":
        status = "failed"
        headline = (f"It failed on attempt {attempts}: {_error_text(err)}. This kind of error is not retried "
                    "automatically: it needs new input or a fix.")
    elif state == "BLOCKED":
        status = "blocked"
        bad = [d for d in deps if d["state"] in ("FAILED", "DEAD_LETTERED", "CANCELLED", "BLOCKED")]
        if bad:
            headline = "It cannot start: it waits for " + ", ".join(
                f"{d.get('title') or d['task_id']} ({d['state'].lower().replace('_', ' ')})" for d in bad) + "."
        else:
            headline = f"It is blocked: {_error_text(err)}."
    elif state == "CANCELLED":
        status = "cancelled"
        headline = "It was cancelled" + (f": {err.get('message')}." if err and err.get("message") else ".")
    elif state == "RETRY_SCHEDULED":
        status = "retrying"
        headline = f"Attempt {attempts} failed ({_error_text(err)}); a new attempt is scheduled for " \
                   f"{task.get('retry_at')}."
    elif state in ("ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED"):
        status = "running"
        agent = executions[-1].get("agent_id") if executions else None
        headline = f"It is running (attempt {attempts}" + (f" on {agent}" if agent else "") + ")."
    else:
        status = "waiting"
        headline = "It has not started yet" + (": it waits for the plan to be approved." if task.get(
            "needs_approval") else ".")
    actions = [
        {"action": "replay", "allowed": state == "DEAD_LETTERED" and not task.get("replaced"),
         "label": "Replay as a new attempt", "why": "after fixing the cause (the retry budget starts again)"},
        {"action": "replan", "allowed": state in ("FAILED", "DEAD_LETTERED", "BLOCKED") and bool(
            task.get("plan_task_id")), "label": "Change the plan", "why": "if the step itself is wrong"},
        {"action": "run_again", "allowed": state in ("FAILED", "DEAD_LETTERED", "CANCELLED"),
         "label": "Run the project again", "why": "if the input was wrong"},
    ]
    return {"status": status, "headline": headline, "facts": facts, "actions": actions,
            "cause": (err or {}).get("code")}


async def explain(system: Any, task_id: str, *, jaeger_url: str, tracing: bool, feed: Any = None) -> dict[str, Any]:
    m = system.manager
    task = await m.get_task(task_id)
    executions = sorted(task.pop("executions", []), key=lambda e: e["attempt"])
    tasks = {t["task_id"]: t for t in await m.list_tasks(task["project_id"])}
    deps = [{"task_id": d, "title": tasks[d].get("title"), "state": tasks[d]["state"]}
            for d in task.get("depends_on", []) if d in tasks]
    dependants = [{"task_id": t["task_id"], "title": t.get("title"), "state": t["state"]} for t in tasks.values()
                  if task_id in t.get("depends_on", []) and not t.get("replaced")]
    events = await task_events(system, task_id, feed)
    messages = await task_messages(system, task_id)
    trace_ids = sorted({tid for msg in messages if (tid := trace_id_of(msg.get("traceparent")))}) or \
        [task_trace_id(task_id)]
    artifacts = []
    for e in executions:
        if e.get("status") == "SUCCEEDED":
            artifacts = [{"artifact_id": r["artifact_id"], "artifact_type": r["artifact_type"],
                          "version": r["version"], "size_bytes": r.get("size_bytes")} for r in e.get("result_refs")]
    exec_view = [{"execution_id": e["execution_id"], "attempt": e["attempt"], "status": e["status"],
                  "agent_id": e.get("agent_id"), "created_at": e.get("created_at"), "updated_at": e.get("updated_at"),
                  "error": e.get("error"), "superseded_by": e.get("superseded_by"),
                  "orphaned_at": e.get("orphaned_at"), "outcome": e.get("outcome"),
                  "late_reports": [{"message_type": ev.get("message_type"), "note": ev.get("note"),
                                    "received_at": ev.get("received_at"), "sender": ev.get("sender")}
                                   for ev in e.get("evidence") or []]} for e in executions]
    return {
        "task": {k: task.get(k) for k in ("task_id", "project_id", "capability", "title", "objective", "state",
                                          "attempts", "retries", "replays", "run", "plan_task_id", "depends_on",
                                          "blocked_by", "last_error", "created_at", "updated_at", "needs_approval",
                                          "replaced", "retry_at")},
        "verdict": verdict(task, executions, deps, dependants),
        "executions": exec_view,
        "messages": messages,
        "timeline": [{"seq": e.get("seq"), "at": e.get("occurred_at"), "event_type": e.get("event_type"),
                      "summary": _summarise_event(e)} for e in events],
        "dependencies": deps,
        "dependants": dependants,
        "trace": {"trace_ids": trace_ids, "tracing": tracing,
                  "links": [f"{jaeger_url.rstrip('/')}/trace/{t}" for t in trace_ids]},
        "artifacts": artifacts,
    }
