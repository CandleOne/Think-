"""AI planning helpers for schedule optimization and routine generation.

This module supports three modes:
1) Claude mode when ANTHROPIC_API_KEY/CLAUDE_API_KEY is configured.
2) OpenAI mode when OPENAI_API_KEY is configured.
3) Deterministic fallback heuristics when no provider key is available.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib import request as urllib_request


@dataclass
class PlanResult:
    mode: str
    summary: str
    updates: list[dict[str, Any]]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse first valid JSON object from arbitrary model text."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start_positions = [idx for idx, ch in enumerate(raw) if ch == "{"]
    for start in start_positions:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        break
    return None


def _get_provider_env() -> tuple[str, str, bool]:
    """Resolve active AI provider from env with safe fallback ordering."""
    requested = (os.environ.get("AI_BRAIN_PROVIDER") or "").strip().lower()
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if requested in {"claude", "anthropic"}:
        model = os.environ.get("CLAUDE_MODEL") or os.environ.get("AI_BRAIN_MODEL") or "claude-3-7-sonnet-latest"
        return "claude", model, has_claude
    if requested == "openai":
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("AI_BRAIN_MODEL") or "gpt-4o-mini"
        return "openai", model, has_openai
    if requested == "heuristic":
        return "heuristic", "heuristic", True

    # Auto mode: prefer Claude when present, then OpenAI, otherwise fallback.
    if has_claude:
        model = os.environ.get("CLAUDE_MODEL") or os.environ.get("AI_BRAIN_MODEL") or "claude-3-7-sonnet-latest"
        return "claude", model, True
    if has_openai:
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("AI_BRAIN_MODEL") or "gpt-4o-mini"
        return "openai", model, True
    return "heuristic", "heuristic", False


def get_ai_runtime_info() -> dict[str, Any]:
    provider, model, configured = _get_provider_env()
    return {
        "provider": provider,
        "model": model,
        "configured": configured,
    }


def _claude_model_candidates() -> list[str]:
    candidates: list[str] = []
    for model in [
        os.environ.get("CLAUDE_MODEL"),
        os.environ.get("AI_BRAIN_MODEL"),
        "claude-sonnet-4-20250514",
        "claude-3-5-sonnet-latest",
    ]:
        m = (model or "").strip()
        if m and m not in candidates:
            candidates.append(m)
    return candidates


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


def _call_openai_json(system_prompt: str, user_prompt: str, max_tokens: int = 1800) -> dict[str, Any] | None:
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
        "max_tokens": _sanitize_token_limit(max_tokens, default=1800),
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
            return _extract_json_object(str(content))
    except Exception:
        return None


def _call_claude_json(system_prompt: str, user_prompt: str, max_tokens: int = 1800) -> dict[str, Any] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
    }
    token_limit = _sanitize_token_limit(max_tokens, default=1800)

    for model in _claude_model_candidates():
        payload = {
            "model": model,
            "max_tokens": token_limit,
            "temperature": 0.2,
            "system": system_prompt + " Return valid JSON only.",
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            f"{base_url}/messages",
            data=data,
            method="POST",
            headers=headers,
        )

        try:
            with urllib_request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body.get("content") or []
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                raw = "\n".join(text_parts).strip()
                if not raw:
                    return None
                return _extract_json_object(raw)
        except HTTPError as err:
            try:
                body_text = err.read().decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
            # Try next candidate when model is not found.
            if err.code == 404 and "not_found_error" in body_text:
                continue
            return None
        except Exception:
            return None
    return None


def _call_ai_json(system_prompt: str, user_prompt: str, max_tokens: int = 1800) -> tuple[str, dict[str, Any] | None]:
    provider, _, configured = _get_provider_env()
    if provider == "claude" and configured:
        return "claude", _call_claude_json(system_prompt, user_prompt, max_tokens=max_tokens)
    if provider == "openai" and configured:
        return "openai", _call_openai_json(system_prompt, user_prompt, max_tokens=max_tokens)

    # Auto fallback attempt when provider is not explicitly configured.
    claude = _call_claude_json(system_prompt, user_prompt, max_tokens=max_tokens)
    if claude:
        return "claude", claude
    openai = _call_openai_json(system_prompt, user_prompt, max_tokens=max_tokens)
    if openai:
        return "openai", openai
    return "heuristic", None


def _sanitize_token_limit(value: Any, default: int = 700) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(64, min(4096, n))


def _call_openai_text(system_prompt: str, user_prompt: str, max_tokens: int = 700) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("AI_BRAIN_MODEL") or "gpt-4o-mini"
    max_tokens = _sanitize_token_limit(max_tokens)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
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
            return str(body["choices"][0]["message"]["content"]).strip()
    except Exception:
        return None


def _call_claude_text(system_prompt: str, user_prompt: str, max_tokens: int = 700) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
    }

    max_tokens = _sanitize_token_limit(max_tokens)

    for model in _claude_model_candidates():
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            f"{base_url}/messages",
            data=data,
            method="POST",
            headers=headers,
        )

        try:
            with urllib_request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body.get("content") or []
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                out = "\n".join(text_parts).strip()
                return out or None
        except HTTPError as err:
            try:
                body_text = err.read().decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
            if err.code == 404 and "not_found_error" in body_text:
                continue
            return None
        except Exception:
            return None
    return None


def query_ai(prompt: str, context: dict[str, Any] | None = None, token_limit: int | None = None) -> dict[str, Any]:
    context = context or {}
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        return {
            "mode": "heuristic",
            "answer": "Please provide a question or request.",
        }

    history = context.get("history") if isinstance(context.get("history"), list) else []
    trimmed_history = []
    for msg in history[-8:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        content = str(msg.get("content") or "").strip()
        if content:
            trimmed_history.append({"role": role, "content": content[:1000]})

    provider, _, configured = _get_provider_env()
    system_prompt = (
        "You are the planning assistant for a life optimization app. "
        "Give practical, actionable, concise advice. "
        "When appropriate, provide numbered steps and mention tradeoffs briefly."
    )
    user_payload = {
        "question": clean_prompt,
        "history": trimmed_history,
        "context": context,
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=True)

    effective_token_limit = _sanitize_token_limit(token_limit, default=700)

    text: str | None = None
    active_mode = provider
    if provider == "claude" and configured:
        text = _call_claude_text(system_prompt, user_prompt, max_tokens=effective_token_limit)
    elif provider == "openai" and configured:
        text = _call_openai_text(system_prompt, user_prompt, max_tokens=effective_token_limit)
    elif provider == "heuristic":
        text = None
    else:
        text = _call_claude_text(system_prompt, user_prompt, max_tokens=effective_token_limit) or _call_openai_text(system_prompt, user_prompt, max_tokens=effective_token_limit)
        if text:
            active_mode = "claude" if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")) else "openai"

    if text:
        return {
            "mode": active_mode,
            "answer": text,
            "token_limit": effective_token_limit,
        }

    lower = clean_prompt.lower()
    if "schedule" in lower or "routine" in lower:
        answer = (
            "Use AI Optimize Tasks first to rebalance timing, then apply only the updates that improve flow. "
            "For routine creation, define one outcome, one cadence, and one review checkpoint to keep it sustainable."
        )
    elif "goal" in lower or "objective" in lower:
        answer = (
            "Break your objective into weekly milestones, map each milestone to 1-3 repeatable tasks, "
            "and track completion in the long-term objective timeline."
        )
    else:
        answer = (
            "AI provider is not configured, so this is heuristic mode. Ask for schedule optimization, routine design, "
            "or objective planning and I will provide structured recommendations."
        )

    return {
        "mode": "heuristic",
        "answer": answer,
        "token_limit": effective_token_limit,
    }


def query_ai_empowered(prompt: str, context: dict[str, Any] | None = None, token_limit: int | None = None) -> dict[str, Any]:
    """Return an AI response that can include structured database edits.

    Expected JSON shape from model:
    {
      "answer": "...",
      "edits": [
        {"op": "update", "table": "custom_items", "id": 10, "fields": {"task_time": "8:00 AM"}},
        {"op": "insert", "table": "goals", "fields": {...}},
        {"op": "delete", "table": "fashion_items", "id": 5}
      ]
    }
    """
    context = context or {}
    clean_prompt = str(prompt or "").strip()
    effective_token_limit = _sanitize_token_limit(token_limit, default=1200)
    if not clean_prompt:
        return {
            "mode": "heuristic",
            "answer": "Please provide a request.",
            "edits": [],
            "token_limit": effective_token_limit,
        }

    def compact_ctx(value, depth=0):
        if depth > 4:
            return None
        if isinstance(value, dict):
            return {str(k): compact_ctx(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [compact_ctx(v, depth + 1) for v in value]
        if isinstance(value, str):
            if len(value) > 220:
                return value[:220] + "..."
            return value
        return value

    user_payload = {
        "request": clean_prompt,
        "context": context,
        "now": datetime.utcnow().isoformat() + "Z",
    }

    provider, llm_result = _call_ai_json(
        system_prompt=(
            "You are an empowered life optimization copilot. "
            "You can propose structured database edits to improve schedules, routines, goals, and planning data. "
            "Always return JSON with keys: answer (string), edits (array). "
            "Each edit must use one of: update|insert|delete and include table. "
            "For update/delete include id. For insert/update include fields object. "
            "Only propose edits that are directly useful for the user's request."
        ),
        user_prompt=json.dumps(user_payload, ensure_ascii=True),
        max_tokens=effective_token_limit,
    )

    # If the full payload is too large for provider processing, retry with compacted text fields.
    if llm_result is None:
        compact_payload = {
            "request": clean_prompt,
            "context": compact_ctx(context),
            "now": datetime.utcnow().isoformat() + "Z",
            "compact_mode": True,
        }
        provider, llm_result = _call_ai_json(
            system_prompt=(
                "You are an empowered life optimization copilot. "
                "The context may be compacted for token safety. "
                "Return JSON with keys: answer (string), edits (array)."
            ),
            user_prompt=json.dumps(compact_payload, ensure_ascii=True),
            max_tokens=effective_token_limit,
        )

    if llm_result and isinstance(llm_result, dict):
        answer = str(llm_result.get("answer") or "").strip()
        edits = llm_result.get("edits") if isinstance(llm_result.get("edits"), list) else []
        clean_edits = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            op = str(edit.get("op") or "").strip().lower()
            table = str(edit.get("table") or "").strip()
            if op not in {"update", "insert", "delete"} or not table:
                continue
            item = {"op": op, "table": table}
            if "id" in edit:
                try:
                    item["id"] = int(edit.get("id"))
                except (TypeError, ValueError):
                    continue
            if "fields" in edit and isinstance(edit.get("fields"), dict):
                item["fields"] = edit.get("fields")
            clean_edits.append(item)

        # If the model gave recommendations but no edits, ask for a strict edit translation.
        if answer and not clean_edits:
            _, edits_only = _call_ai_json(
                system_prompt=(
                    "Convert a planning recommendation into executable DB edits. "
                    "Return JSON object with key edits (array) only. "
                    "Use ops update|insert|delete and include table, id (for update/delete), and fields (for insert/update)."
                ),
                user_prompt=json.dumps(
                    {
                        "request": clean_prompt,
                        "recommendation": answer,
                        "context": compact_ctx(context),
                    },
                    ensure_ascii=True,
                ),
                max_tokens=effective_token_limit,
            )
            if isinstance(edits_only, dict) and isinstance(edits_only.get("edits"), list):
                for edit in edits_only.get("edits"):
                    if not isinstance(edit, dict):
                        continue
                    op = str(edit.get("op") or "").strip().lower()
                    table = str(edit.get("table") or "").strip()
                    if op not in {"update", "insert", "delete"} or not table:
                        continue
                    item = {"op": op, "table": table}
                    if "id" in edit:
                        try:
                            item["id"] = int(edit.get("id"))
                        except (TypeError, ValueError):
                            continue
                    if "fields" in edit and isinstance(edit.get("fields"), dict):
                        item["fields"] = edit.get("fields")
                    clean_edits.append(item)

        if answer or clean_edits:
            return {
                "mode": provider,
                "answer": answer or "I prepared an empowered plan.",
                "edits": clean_edits,
                "token_limit": effective_token_limit,
            }

    # If structured output fails, still return provider answer via normal query path.
    basic = query_ai(clean_prompt, context, token_limit=effective_token_limit)
    if basic.get("mode") != "heuristic":
        return {
            "mode": basic.get("mode", "heuristic"),
            "answer": basic.get("answer", ""),
            "edits": [],
            "token_limit": effective_token_limit,
        }

    # Heuristic fallback when provider call fails.
    return {
        "mode": "heuristic",
        "answer": (
            "I can propose and apply structured edits across your app data. "
            "Ask for specific outcomes (for example: rebalance weekly routine, tighten goal milestones, or refactor section priorities)."
        ),
        "edits": [],
        "token_limit": effective_token_limit,
    }


def optimize_schedule(tasks: list[dict[str, Any]], preferences: dict[str, Any] | None = None) -> PlanResult:
    preferences = preferences or {}
    provider, llm_result = _call_ai_json(
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
                mode=provider,
                summary=str(llm_result.get("summary", f"Generated {len(clean)} AI schedule updates.")),
                updates=clean,
            )

    return _heuristic_schedule(tasks, preferences)


def build_routine_plan(payload: dict[str, Any], existing_sections: list[dict[str, Any]]) -> dict[str, Any]:
    title = str(payload.get("title") or "AI Routine").strip()
    goal = str(payload.get("goal") or "Improve consistency").strip()
    cadence = str(payload.get("cadence") or "daily").strip().lower()
    minutes = int(payload.get("available_minutes") or 90)

    provider, llm_result = _call_ai_json(
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
            "mode": provider,
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
