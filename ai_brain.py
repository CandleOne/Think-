"""AI planning helpers for schedule optimization and routine generation.

This module supports two modes:
1) LLM mode when OPENAI_API_KEY is configured.
2) Deterministic fallback heuristics when no key is available.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib import request as urllib_request


@dataclass
class PlanResult:
    mode: str
    summary: str
    updates: list[dict[str, Any]]


def _parse_time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip().upper()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", value)
    if not m:
        return None

    hours = int(m.group(1))
    minutes = int(m.group(2) or 0)
    period = m.group(3)

    if period == "PM" and hours != 12:
        hours += 12
    if period == "AM" and hours == 12:
        hours = 0
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None
    return hours * 60 + minutes


def _minutes_to_12h(total_minutes: int) -> str:
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    period = "AM" if hours < 12 else "PM"
    h12 = hours % 12 or 12
    return f"{h12}:{minutes:02d} {period}"


def _default_duration_for_task(task: dict[str, Any]) -> int:
    subgroup = (task.get("subgroup") or "").lower()
    if subgroup in {"morning", "midday"}:
        return 40
    if subgroup in {"afternoon", "evening"}:
        return 45
    return 35


def _heuristic_schedule(tasks: list[dict[str, Any]], preferences: dict[str, Any]) -> PlanResult:
    start_time = _parse_time_to_minutes(str(preferences.get("start_time", "7:00 AM")))
    end_time = _parse_time_to_minutes(str(preferences.get("end_time", "10:00 PM")))
    break_minutes = int(preferences.get("break_minutes", 10) or 10)

    if start_time is None:
        start_time = 7 * 60
    if end_time is None:
        end_time = 22 * 60
    if end_time <= start_time:
        end_time = start_time + 8 * 60

    # Keep routine grouping and prioritize by existing sort order.
    tasks_sorted = sorted(tasks, key=lambda t: (t.get("section_key", ""), t.get("sort_order") or 0, t.get("name", "")))

    cursor = start_time
    updates: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks_sorted):
        duration = _default_duration_for_task(task)
        if cursor + duration > end_time:
            cursor = start_time

        suggested_time = _minutes_to_12h(cursor)
        subgroup = task.get("subgroup")
        if not subgroup:
            hour = cursor // 60
            if hour < 12:
                subgroup = "Morning"
            elif hour < 14:
                subgroup = "Midday"
            elif hour < 18:
                subgroup = "Afternoon"
            else:
                subgroup = "Evening"

        updates.append(
            {
                "id": task["id"],
                "section_key": task["section_key"],
                "name": task.get("name", "Task"),
                "task_time": suggested_time,
                "subgroup": subgroup,
                "sort_order": idx,
                "reason": "Heuristic spacing for consistent daily workload",
            }
        )
        cursor += duration + break_minutes

    summary = (
        f"Generated {len(updates)} schedule recommendations using fallback heuristics "
        f"between {_minutes_to_12h(start_time)} and {_minutes_to_12h(end_time)}."
    )
    return PlanResult(mode="heuristic", summary=summary, updates=updates)


def _call_openai_json(system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("AI_BRAIN_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{base_url}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception:
        return None


def optimize_schedule(tasks: list[dict[str, Any]], preferences: dict[str, Any] | None = None) -> PlanResult:
    preferences = preferences or {}
    llm_result = _call_openai_json(
        system_prompt=(
            "You optimize personal schedules. Return JSON with keys: summary (string), updates (array). "
            "Each update object must include id, section_key, task_time (H:MM AM/PM), subgroup, sort_order, reason."
        ),
        user_prompt=json.dumps(
            {
                "preferences": preferences,
                "tasks": tasks,
                "now": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=True,
        ),
    )

    if llm_result and isinstance(llm_result.get("updates"), list):
        updates = llm_result.get("updates", [])
        # Keep only updates with required keys.
        clean = []
        for u in updates:
            if not isinstance(u, dict):
                continue
            if "id" not in u or "section_key" not in u or "task_time" not in u:
                continue
            clean.append(
                {
                    "id": int(u["id"]),
                    "section_key": str(u["section_key"]),
                    "name": str(u.get("name", "Task")),
                    "task_time": str(u["task_time"]),
                    "subgroup": str(u.get("subgroup", "")),
                    "sort_order": int(u.get("sort_order", 0) or 0),
                    "reason": str(u.get("reason", "AI schedule optimization")),
                }
            )
        if clean:
            return PlanResult(
                mode="llm",
                summary=str(llm_result.get("summary", f"Generated {len(clean)} AI schedule updates.")),
                updates=clean,
            )

    return _heuristic_schedule(tasks, preferences)


def build_routine_plan(payload: dict[str, Any], existing_sections: list[dict[str, Any]]) -> dict[str, Any]:
    title = str(payload.get("title") or "AI Routine").strip()
    goal = str(payload.get("goal") or "Improve consistency").strip()
    cadence = str(payload.get("cadence") or "daily").strip().lower()
    minutes = int(payload.get("available_minutes") or 90)

    llm_result = _call_openai_json(
        system_prompt=(
            "You design actionable routines. Return JSON with keys: section_label, group_name, section_type, summary, items. "
            "items is an array of objects with name, task_time, task_interval, subgroup, notes, status_color."
        ),
        user_prompt=json.dumps(
            {
                "request": {
                    "title": title,
                    "goal": goal,
                    "cadence": cadence,
                    "available_minutes": minutes,
                },
                "existing_sections": existing_sections,
            },
            ensure_ascii=True,
        ),
    )

    if llm_result and isinstance(llm_result.get("items"), list) and llm_result["items"]:
        plan = {
            "mode": "llm",
            "section_label": str(llm_result.get("section_label") or title),
            "group_name": str(llm_result.get("group_name") or "Routines"),
            "section_type": str(llm_result.get("section_type") or "schedule"),
            "summary": str(llm_result.get("summary") or f"AI routine generated for {goal}."),
            "items": [],
        }
        for item in llm_result["items"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "Routine task").strip()
            if not name:
                continue
            plan["items"].append(
                {
                    "name": name,
                    "task_time": str(item.get("task_time") or ""),
                    "task_interval": str(item.get("task_interval") or cadence),
                    "subgroup": str(item.get("subgroup") or ""),
                    "notes": str(item.get("notes") or ""),
                    "status_color": str(item.get("status_color") or "blue"),
                }
            )
        if plan["items"]:
            return plan

    # Fallback deterministic routine scaffold.
    section_label = title
    group_name = str(payload.get("group_name") or "Routines")
    base = [
        ("Planning", "7:00 AM", "Morning", "Set priorities for the day"),
        ("Deep Work Block", "9:00 AM", "Morning", f"Focused work for goal: {goal}"),
        ("Review and Log", "8:00 PM", "Evening", "Measure progress and adjust tomorrow"),
    ]
    if minutes < 60:
        base = base[:2]
    return {
        "mode": "heuristic",
        "section_label": section_label,
        "group_name": group_name,
        "section_type": "schedule",
        "summary": f"Generated fallback routine for {goal} with {len(base)} tasks.",
        "items": [
            {
                "name": f"{title}: {name}",
                "task_time": time,
                "task_interval": cadence,
                "subgroup": subgroup,
                "notes": notes,
                "status_color": "blue",
            }
            for (name, time, subgroup, notes) in base
        ],
    }


def apply_schedule_updates(db_conn: Any, updates: list[dict[str, Any]]) -> int:
    applied = 0
    for idx, upd in enumerate(updates):
        cur = db_conn.execute(
            """
            UPDATE custom_items
            SET task_time=?, subgroup=?, sort_order=?, updated_at=datetime('now')
            WHERE id=? AND section_key=?
            """,
            (
                upd.get("task_time"),
                upd.get("subgroup") or None,
                int(upd.get("sort_order", idx)),
                int(upd["id"]),
                str(upd["section_key"]),
            ),
        )
        if cur.rowcount:
            applied += 1
    return applied
