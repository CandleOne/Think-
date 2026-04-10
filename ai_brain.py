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


# ── Web Search ────────────────────────────────────────────────────────────────

def web_search(query: str, num_results: int = 5) -> list[dict[str, str]]:
    """Search the web via Tavily Search API.

    Requires TAVILY_API_KEY environment variable.
    Returns list of {title, link, snippet}.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": min(num_results, 10),
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": False,
    }
    req = urllib_request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append({
                    "title": str(item.get("title", "")),
                    "link": str(item.get("url", "")),
                    "snippet": str(item.get("content", "")),
                })
            return results
    except HTTPError:
        return []
    except Exception:
        return []


def _parse_schedule_minutes(schedule_context: list[dict[str, Any]] | None) -> list[int]:
    mins: list[int] = []
    for item in schedule_context or []:
        if not isinstance(item, dict):
            continue
        val = _parse_time_to_minutes(str(item.get("task_time") or ""))
        if val is not None:
            mins.append(val)
    mins = sorted(set(mins))
    return mins


def _derive_hour_blocks(schedule_context: list[dict[str, Any]] | None) -> list[tuple[int, int]]:
    mins = _parse_schedule_minutes(schedule_context)
    blocks: list[tuple[int, int]] = []
    if mins:
        anchors = mins[:4]
        for m in anchors:
            blocks.append((m, m + 60))
    else:
        defaults = [7 * 60, 12 * 60 + 30, 18 * 60, 20 * 60 + 30]
        blocks = [(m, m + 60) for m in defaults]
    return blocks


def _build_daily_plan_lines(
    instruction_steps: list[str],
    schedule_context: list[dict[str, Any]] | None,
    seed: int = 0,
) -> list[str]:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    steps = [s for s in instruction_steps if s] or ["Execute focused practice for this objective"]
    blocks = _derive_hour_blocks(schedule_context)
    lines: list[str] = []
    for i, day in enumerate(days):
        start, end = blocks[(seed + i) % len(blocks)]
        step = steps[(seed + i) % len(steps)]
        lines.append(f"{day} {_minutes_to_12h(start)} - {_minutes_to_12h(end)}: {step}")
    return lines


def _build_schedule_fit_notes(
    schedule_context: list[dict[str, Any]] | None,
    daily_plan: list[str],
) -> list[str]:
    blocks = _derive_hour_blocks(schedule_context)
    block_labels = [f"{_minutes_to_12h(s)}-{_minutes_to_12h(e)}" for s, e in blocks[:3]]
    notes = [
        f"Anchored to existing routine windows: {', '.join(block_labels)}.",
        "Use these blocks after fixed schedule tasks to maintain consistency.",
        "If a day is overloaded, move that session to the nearest matching block on the next day.",
    ]
    if daily_plan:
        notes.append("Daily plan is ordered for progressive skill build and weekly consolidation.")
    return notes


# ── Query normalisation ────────────────────────────────────────────────────────

_STRIP_PREFIXES = re.compile(
    r"^(?:i\s+want\s+to|i\s+would\s+like\s+to|i(?:'d|\s+would)\s+like\s+to"
    r"|help\s+me|please\s+help\s+me|can\s+you|could\s+you|i\s+need\s+to"
    r"|i\s+am\s+trying\s+to|i(?:'m|\s+am)\s+looking\s+to"
    r"|show\s+me\s+how\s+to|teach\s+me\s+(?:how\s+to\s+)?"
    r"|let(?:'s|\s+us)|i(?:'d|\s+would)\s+love\s+to)\s+",
    re.IGNORECASE,
)

_STRIP_SUFFIXES = re.compile(
    r"\.\s*(?:create|make|build|generate|give\s+me|set\s+up|produce)"
    r".*?(?:goal|plan|roadmap|objective|lto|schedule|checklist).*$",
    re.IGNORECASE,
)

_TIME_PHRASES = re.compile(
    r"\b(?:over\s+the\s+next|within\s+(?:the\s+next\s+)?"
    r"|in\s+(?:the\s+next\s+)?|for\s+(?:the\s+next\s+)?)"
    r"\s*\d*\s*(?:day|week|month|year)s?\b",
    re.IGNORECASE,
)

_FLUFF = re.compile(
    r"\b(?:really|actually|basically|just|definitely|maybe"
    r"|as\s+soon\s+as\s+possible|asap)\b",
    re.IGNORECASE,
)


def _extract_topic(raw: str) -> str:
    """Distill a conversational prompt into a concise topic phrase.

    e.g. "i want to learn the basics of making sushi over the next month.
          create a long term goal for me to do that"
    → "learn the basics of making sushi"
    """
    text = str(raw or "").strip()
    if not text:
        return "Research Topic"

    # Remove trailing goal-creation requests
    text = _STRIP_SUFFIXES.sub("", text).strip().rstrip(".")

    # Remove conversational prefixes
    text = _STRIP_PREFIXES.sub("", text).strip()

    # Remove timeframe qualifiers
    text = _TIME_PHRASES.sub("", text).strip()

    # Remove filler words
    text = _FLUFF.sub("", text).strip()

    # Collapse whitespace
    text = re.sub(r"\s{2,}", " ", text).strip(" .,;:!?")

    # Capitalize nicely
    if text:
        text = text[0].upper() + text[1:]

    return text or "Research Topic"


# ── Domain-specific heuristic content ──────────────────────────────────────────

def _domain_heuristics(topic: str, source_titles: list[str]) -> dict[str, Any]:
    """Return domain-specific subgoals, shopping list, prerequisites, etc."""
    t = topic.lower()
    ref_1 = source_titles[0] if len(source_titles) > 0 else f"core {topic} reference"
    ref_2 = source_titles[1] if len(source_titles) > 1 else f"intermediate {topic} reference"
    ref_3 = source_titles[2] if len(source_titles) > 2 else f"advanced {topic} reference"

    # --- Sushi / Japanese cooking ---
    if any(k in t for k in ["sushi", "maki", "nigiri", "sashimi"]):
        return {
            "shopping_list": [
                "Sushi-grade fish (salmon, tuna) from a trusted fishmonger",
                "Short-grain Japanese rice (Koshihikari or Calrose)",
                "Rice vinegar, sugar, salt for seasoning",
                "Nori (roasted seaweed sheets)",
                "Bamboo rolling mat (makisu)",
                "Sharp sushi knife (yanagiba or santoku)",
                "Rice paddle (shamoji) and hangiri (wooden bowl) or large flat bowl",
                "Soy sauce, wasabi, pickled ginger (gari)",
                "Plastic wrap and damp towel for rolling",
            ],
            "prerequisites": [
                "Basic kitchen knife safety and cutting technique",
                "Ability to cook rice on stovetop or rice cooker",
                "Understanding of food safety for raw fish handling",
                "Access to a clean, spacious work surface",
            ],
            "subgoals": [
                {
                    "title": "Foundation: Master sushi rice preparation",
                    "description": "Learn to cook, season, and cool sushi rice to the correct texture and flavour — the single most important sushi skill.",
                    "time_commitment_hours": 4.0,
                    "target_date_hint": "Week 1",
                    "roadmap": [
                        f"Study rice preparation fundamentals from: {ref_1}",
                        "Practice rinsing, soaking, and cooking short-grain rice 3 times",
                        "Mix seasoned vinegar (su) and fan rice to body temperature",
                        "Taste-test and adjust vinegar-sugar-salt ratio",
                    ],
                    "instruction_steps": [
                        "Rinse rice until water runs clear (4-5 washes)",
                        "Soak 30 min, cook at 1:1 water ratio",
                        "Mix vinegar while rice is hot using cutting motions",
                        "Fan rice to cool to body temp — grains should be glossy, not mushy",
                    ],
                },
                {
                    "title": "Knife skills and fish preparation",
                    "description": "Develop safe, clean slicing technique for raw fish fillets — proper cuts affect texture and presentation.",
                    "time_commitment_hours": 5.0,
                    "target_date_hint": "Week 1-2",
                    "roadmap": [
                        f"Review knife technique references: {ref_2}",
                        "Practice pulling cuts on cucumber and avocado",
                        "Slice salmon fillet into nigiri-sized pieces (finger width, 3mm thick)",
                        "Practice consistent slice angle and thickness",
                    ],
                    "instruction_steps": [
                        "Sharpen knife before each session",
                        "Use a single long pulling stroke — never saw back and forth",
                        "Keep fish cold; return to fridge between batches",
                        "Aim for uniform 3mm slices at 20-degree angle",
                    ],
                },
                {
                    "title": "Maki rolls: basic rolling technique",
                    "description": "Learn to assemble and roll hosomaki (thin rolls) and futomaki (thick rolls) with even pressure and clean cuts.",
                    "time_commitment_hours": 6.0,
                    "target_date_hint": "Week 2-3",
                    "roadmap": [
                        f"Follow rolling tutorials from: {ref_3}",
                        "Make 3 batches of hosomaki (cucumber, avocado, tuna)",
                        "Progress to futomaki with 3-4 fillings",
                        "Practice cutting rolls into 6 or 8 even pieces",
                    ],
                    "instruction_steps": [
                        "Place nori shiny-side down on mat, spread rice leaving 1cm border",
                        "Lay fillings in a line across the centre",
                        "Roll with firm, even pressure — lift mat, don't roll it in",
                        "Wet knife before each cut; wipe between slices",
                    ],
                },
                {
                    "title": "Nigiri shaping and presentation",
                    "description": "Hand-shape nigiri with correct rice density, wasabi placement, and fish drape.",
                    "time_commitment_hours": 5.0,
                    "target_date_hint": "Week 3-4",
                    "roadmap": [
                        "Practice shaping rice oblongs by hand (20g each)",
                        "Apply thin wasabi line and drape fish slice",
                        "Refine two-finger press technique for consistent density",
                        "Plate 6-piece sets for visual consistency check",
                    ],
                    "instruction_steps": [
                        "Wet hands in vinegar water to prevent sticking",
                        "Form rice gently — squeeze too hard and it becomes gummy",
                        "Fish should overhang rice by ~5mm on each end",
                        "Serve within 5 minutes of shaping for best texture",
                    ],
                },
                {
                    "title": "Full sushi dinner: end-to-end execution",
                    "description": "Plan, prep, and serve a complete sushi meal combining maki, nigiri, and sides within a 90-minute window.",
                    "time_commitment_hours": 10.0,
                    "target_date_hint": "Week 4+",
                    "roadmap": [
                        "Create a menu: 2 maki types, 2 nigiri types, miso soup, edamame",
                        "Prep mise en place and timeline (rice first, fish last)",
                        "Execute rolling and shaping within time target",
                        "Plate, photograph, and self-score presentation and taste",
                    ],
                    "instruction_steps": [
                        "Start rice 60 min before serving",
                        "Slice all fish while rice cools",
                        "Roll maki first (they hold better), then shape nigiri last",
                        "Score each piece 1-5 on shape, rice texture, and taste",
                    ],
                },
            ],
        }

    # --- Cooking / general food ---
    if any(k in t for k in ["cook", "bak", "kitchen", "food", "recipe", "meal"]):
        return {
            "shopping_list": [
                "Chef's knife (8-inch) and cutting board",
                "Stainless steel or cast-iron skillet",
                "Saucepan and stockpot",
                "Measuring cups and spoons",
                "Instant-read thermometer",
                "Wooden spoons and silicone spatula",
                "Basic pantry: olive oil, salt, pepper, garlic, onions, butter",
            ],
            "prerequisites": [
                "Basic kitchen safety awareness (burns, cuts, cross-contamination)",
                "Ability to follow a written recipe",
                "Access to a stove/oven and basic cookware",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Fitness ---
    if any(k in t for k in ["fitness", "workout", "exercise", "gym", "strength",
                             "run", "muscle", "weight loss", "cardio", "yoga"]):
        return {
            "shopping_list": [
                "Comfortable athletic shoes appropriate for your activity",
                "Resistance bands (light, medium, heavy)",
                "Yoga mat or exercise mat",
                "Water bottle (32 oz minimum)",
                "Workout log notebook or tracking app",
            ],
            "prerequisites": [
                "Medical clearance if you have pre-existing conditions",
                "Baseline fitness assessment (max push-ups, mile time, flexibility)",
                "Understanding of proper warm-up and cool-down routines",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Programming / tech ---
    if any(k in t for k in ["programming", "coding", "software", "python",
                             "javascript", "web dev", "app dev", "code"]):
        return {
            "shopping_list": [
                "Computer with modern OS and reliable internet",
                "Code editor (VS Code recommended — free)",
                "GitHub account for version control",
                "Optional: second monitor for documentation reference",
            ],
            "prerequisites": [
                "Basic computer literacy and file management",
                "Typing proficiency (40+ WPM recommended)",
                "Familiarity with using a web browser and terminal/command line",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Finance / investing ---
    if any(k in t for k in ["finance", "invest", "stock", "budget", "saving",
                             "money", "trading", "crypto", "portfolio"]):
        return {
            "shopping_list": [
                "Spreadsheet software or budgeting app (YNAB, Mint, or Google Sheets)",
                "Brokerage account (Fidelity, Schwab, or Vanguard)",
                "Notepad for tracking financial decisions and rationale",
            ],
            "prerequisites": [
                "Basic understanding of income, expenses, and net worth",
                "Emergency fund covering 1-3 months of expenses",
                "Awareness of tax implications in your jurisdiction",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Music ---
    if any(k in t for k in ["music", "guitar", "piano", "drum", "sing",
                             "instrument", "song", "compose"]):
        return {
            "shopping_list": [
                "Your instrument (or access to one for practice)",
                "Tuner / metronome app",
                "Music stand and printed sheet music or tabs",
                "Audio recorder or phone for self-review",
            ],
            "prerequisites": [
                "Basic understanding of musical notation or tablature",
                "Ability to commit to daily 15-30 minute practice sessions",
                "A quiet practice space",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Language learning ---
    if any(k in t for k in ["language", "spanish", "french", "japanese",
                             "german", "chinese", "korean", "italian",
                             "learn english", "esl", "vocabulary"]):
        return {
            "shopping_list": [
                "Language learning app (Anki, Duolingo, or Pimsleur)",
                "Pocket phrasebook or dictionary",
                "Notebook dedicated to vocabulary and grammar notes",
                "Headphones for listening practice",
            ],
            "prerequisites": [
                "Motivation and clear reason for learning (travel, career, heritage)",
                "Daily 20-minute practice slot identified",
                "Baseline self-assessment of current level",
            ],
            "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
        }

    # --- Fallback / generic ---
    return {
        "shopping_list": [],
        "prerequisites": [
            f"Baseline familiarity with {topic}",
            "Weekly calendar blocks reserved for focused practice",
            "Tracking system for progress and blockers",
            "Defined review cadence (daily check-ins + weekly retro)",
        ],
        "subgoals": _generic_subgoals(topic, ref_1, ref_2, ref_3),
    }


def _generic_subgoals(topic: str, ref_1: str, ref_2: str, ref_3: str) -> list[dict]:
    """Return 5 solid topic-specific subgoals using the topic name in every field."""
    return [
        {
            "title": f"Foundation: Research and define success criteria for {topic}",
            "description": f"Gather foundational knowledge about {topic} and define clear, measurable criteria for what 'done' looks like.",
            "time_commitment_hours": 5.0,
            "target_date_hint": "Week 1",
            "roadmap": [
                f"Read and summarise key concepts from: {ref_1}",
                f"Define 3 measurable outcomes that prove competence in {topic}",
                f"Run one baseline attempt at {topic} and score yourself honestly",
            ],
            "instruction_steps": [
                "Create a one-page reference sheet of core concepts",
                "Write down your success criteria in concrete terms",
                "Score your baseline attempt and list your 3 biggest gaps",
            ],
        },
        {
            "title": f"Core skill development for {topic}",
            "description": f"Build the fundamental skills required for {topic} through focused, repetitive practice sessions.",
            "time_commitment_hours": 7.0,
            "target_date_hint": "Week 2",
            "roadmap": [
                f"Complete 3-4 focused practice sessions using: {ref_2}",
                f"Track quality and error rate for each {topic} session",
                f"Hit a minimum consistency threshold before moving on",
            ],
            "instruction_steps": [
                "Time-box each practice session to 30-60 minutes",
                "Record one key takeaway and one mistake per session",
                "Repeat the weakest exercise at the end of each session",
            ],
        },
        {
            "title": f"Intermediate integration for {topic}",
            "description": f"Combine foundational skills into complete {topic} workflows with increasing complexity.",
            "time_commitment_hours": 8.0,
            "target_date_hint": "Week 3",
            "roadmap": [
                f"Integrate multiple skills using patterns from: {ref_3}",
                f"Add one new complexity variable to each {topic} session",
                "Review and fix recurring failure points",
            ],
            "instruction_steps": [
                "Start each session with a quick fundamentals warm-up",
                "Run through the complete workflow twice with quality scoring",
                "Identify and patch the top recurring bottleneck",
            ],
        },
        {
            "title": f"Real-world application of {topic}",
            "description": f"Apply {topic} under realistic constraints — time pressure, full complexity, real stakes.",
            "time_commitment_hours": 6.0,
            "target_date_hint": "Week 4",
            "roadmap": [
                f"Simulate a real-world {topic} scenario with strict time limits",
                "Execute the full workflow and score against your success criteria",
                "Compare results to your baseline and measure improvement",
            ],
            "instruction_steps": [
                "Set hard start/end times for each practice run",
                "Use a rubric to score yourself after each attempt",
                "Change only one variable between attempts",
            ],
        },
        {
            "title": f"Mastery validation and maintenance plan for {topic}",
            "description": f"Confirm you've met your success criteria for {topic} and set up a recurring practice schedule to maintain the skill.",
            "time_commitment_hours": 4.0,
            "target_date_hint": "Week 5-6",
            "roadmap": [
                "Run a final benchmark against your original success criteria",
                "Document your process as a repeatable checklist/SOP",
                "Schedule weekly maintenance sessions and a monthly review",
            ],
            "instruction_steps": [
                "Score your final benchmark and compare to your Week 1 baseline",
                "Finalise your SOP — keep it short and actionable",
                "Add recurring calendar events for maintenance practice",
            ],
        },
    ]


def _heuristic_research_goals(
    topic: str,
    search_results: list[dict[str, str]],
    life_area_name: str | None = None,
    schedule_context: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build practical fallback goals when an AI provider is not configured."""
    clean_topic = _extract_topic(topic)
    area = str(life_area_name or "General").strip() or "General"

    source_insights = [
        str((r or {}).get("snippet") or "").strip()
        for r in search_results[:6]
        if str((r or {}).get("snippet") or "").strip()
    ]
    source_titles = [
        str((r or {}).get("title") or "").strip()
        for r in search_results[:6]
        if str((r or {}).get("title") or "").strip()
    ]
    merged_insight = " ".join(source_insights)[:400]

    description = (
        f"Comprehensive long-term roadmap to achieve {clean_topic} in {area}. "
        "This plan is structured for consistent execution with measurable progress."
    )
    if merged_insight:
        description += f" Research context: {merged_insight}"

    domain = _domain_heuristics(clean_topic, source_titles)

    roadmap = [
        f"Week 1: Define baseline skill level and completion criteria for {clean_topic}",
        f"Week 1: Set up environment, tools, and tracking for {clean_topic}",
        f"Week 2: Learn core theory and terminology of {clean_topic}",
        f"Week 2: Practice foundational {clean_topic} techniques with quality thresholds",
        f"Week 3: Increase practice volume for {clean_topic} while preserving quality",
        "Week 3: Add diagnostic review after each practice block",
        f"Week 4: Simulate real-world {clean_topic} execution with time limits",
        "Week 4: Identify recurring failures and root causes",
        f"Week 5: Isolate weak {clean_topic} components into targeted drills",
        "Week 5: Reintegrate improved components into full workflow",
        "Week 6: Add complexity and edge-case handling",
        f"Week 6: Benchmark {clean_topic} performance versus completion criteria",
        "Week 7: Optimize speed/quality trade-offs with controlled experiments",
        f"Week 7: Document standardised repeatable {clean_topic} process",
        "Week 8: Final validation run with objective scoring",
        "Week 8: Publish final playbook and maintenance cadence",
    ]

    instruction_steps = [
        "Define one measurable success metric for every session",
        "Run a pre-session checklist to remove setup friction",
        "Time-box focused work and keep a completion log",
        "After each session, record one failure and one correction",
        "Convert recurring errors into explicit drill exercises",
        "Use weekly retrospectives to update next-week priorities",
        "Escalate complexity only after baseline quality is stable",
        "Keep one buffer day each week for spillover and recovery",
        "Audit outcomes against goals every Sunday",
        "Refactor process documentation as skills improve",
    ]

    prerequisites = domain.get("prerequisites", [
        f"Baseline familiarity with {clean_topic}",
        "Weekly calendar blocks reserved for focused execution",
        "Tracking system for metrics, blockers, and outcomes",
        "A defined review cadence (daily check-ins + weekly retro)",
    ])

    shopping_list = domain.get("shopping_list", [])

    context_notes = [
        f"Optimize for {area} constraints and available time",
        "Prefer consistency of execution over occasional intensity",
        "Reduce scope before skipping planned sessions",
        "Use objective scoring criteria to avoid vague progress",
    ]

    daily_plan = _build_daily_plan_lines(instruction_steps, schedule_context, seed=0)
    schedule_fit_notes = _build_schedule_fit_notes(schedule_context, daily_plan)

    subgoals = domain.get("subgoals", [])
    for i, sg in enumerate(subgoals):
        sg_steps = _to_string_list(sg.get("instruction_steps"), max_items=10)
        sg["daily_plan"] = _build_daily_plan_lines(sg_steps, schedule_context, seed=i)

    return [{
        "title": f"Master Plan: {clean_topic}",
        "description": description,
        "priority": 5,
        "difficulty": 8,
        "time_commitment_hours": 36.0,
        "target_date_hint": "2 months",
        "roadmap": roadmap,
        "instruction_steps": instruction_steps,
        "prerequisites": prerequisites,
        "shopping_list": shopping_list,
        "context_notes": context_notes,
        "daily_plan": daily_plan,
        "schedule_fit_notes": schedule_fit_notes,
        "subgoals": subgoals,
    }]


def _to_string_list(value: Any, max_items: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _normalize_research_goal(
    goal: dict[str, Any],
    topic: str,
    life_area_name: str | None = None,
    schedule_context: list[dict[str, Any]] | None = None,
    seed: int = 0,
) -> dict[str, Any] | None:
    title = str(goal.get("title") or "").strip()
    if not title:
        return None

    description = str(goal.get("description") or "").strip()
    priority = min(5, max(1, int(goal.get("priority") or 3)))
    difficulty = min(10, max(1, int(goal.get("difficulty") or 5)))
    hours = max(0, float(goal.get("time_commitment_hours") or 0))
    target = str(goal.get("target_date_hint") or "").strip()

    roadmap = _to_string_list(goal.get("roadmap"), max_items=28)
    instruction_steps = _to_string_list(goal.get("instruction_steps"), max_items=30)
    prerequisites = _to_string_list(goal.get("prerequisites"), max_items=8)
    shopping_list = _to_string_list(goal.get("shopping_list"), max_items=12)
    context_notes = _to_string_list(goal.get("context_notes"), max_items=8)
    daily_plan = _to_string_list(goal.get("daily_plan"), max_items=28)
    schedule_fit_notes = _to_string_list(goal.get("schedule_fit_notes"), max_items=8)

    if not instruction_steps and roadmap:
        instruction_steps = [f"Execute: {step}" for step in roadmap[:4]]
    if not roadmap and instruction_steps:
        roadmap = [f"Step {i+1}: {step}" for i, step in enumerate(instruction_steps[:4])]
    if not prerequisites:
        prerequisites = [
            f"Baseline understanding of {topic}",
            "A weekly execution window and progress tracker",
        ]
    if not context_notes:
        area = str(life_area_name or "General").strip() or "General"
        context_notes = [
            f"Tailor execution to {area} priorities",
            "Keep scope small enough for consistent weekly completion",
        ]
    if not daily_plan:
        daily_plan = _build_daily_plan_lines(instruction_steps, schedule_context, seed=seed)
    if not schedule_fit_notes:
        schedule_fit_notes = _build_schedule_fit_notes(schedule_context, daily_plan)

    raw_subgoals = goal.get("subgoals") if isinstance(goal.get("subgoals"), list) else []
    subgoals: list[dict[str, Any]] = []
    for idx, sg in enumerate(raw_subgoals[:14]):
        if not isinstance(sg, dict):
            continue
        sg_title = str(sg.get("title") or "").strip()
        if not sg_title:
            continue
        sg_desc = str(sg.get("description") or "").strip()
        sg_roadmap = _to_string_list(sg.get("roadmap"), max_items=14)
        sg_steps = _to_string_list(sg.get("instruction_steps"), max_items=16)
        sg_daily = _to_string_list(sg.get("daily_plan"), max_items=10)
        if not sg_daily:
            sg_daily = _build_daily_plan_lines(sg_steps or instruction_steps, schedule_context, seed=seed + idx)
        subgoals.append({
            "title": sg_title,
            "description": sg_desc,
            "time_commitment_hours": max(0, float(sg.get("time_commitment_hours") or 0)),
            "target_date_hint": str(sg.get("target_date_hint") or "").strip(),
            "roadmap": sg_roadmap,
            "instruction_steps": sg_steps,
            "daily_plan": sg_daily,
        })

    if not subgoals:
        # Derive chapter-like subgoals from roadmap chunks when model omits subgoals.
        chunk_size = 3
        for idx in range(0, len(roadmap), chunk_size):
            chunk = roadmap[idx:idx + chunk_size]
            if not chunk:
                continue
            title_idx = (idx // chunk_size) + 1
            sg_steps = [f"Execute milestone: {step}" for step in chunk]
            subgoals.append({
                "title": f"Subgoal {title_idx}: {chunk[0][:80]}",
                "description": "Focused execution block derived from the master roadmap.",
                "time_commitment_hours": 0.0,
                "target_date_hint": "",
                "roadmap": chunk,
                "instruction_steps": sg_steps,
                "daily_plan": _build_daily_plan_lines(sg_steps, schedule_context, seed=seed + title_idx),
            })

    return {
        "title": title,
        "description": description,
        "priority": priority,
        "difficulty": difficulty,
        "time_commitment_hours": hours,
        "target_date_hint": target,
        "roadmap": roadmap,
        "instruction_steps": instruction_steps,
        "prerequisites": prerequisites,
        "shopping_list": shopping_list,
        "context_notes": context_notes,
        "daily_plan": daily_plan,
        "schedule_fit_notes": schedule_fit_notes,
        "subgoals": subgoals,
    }


def _consolidate_research_goals(goals: list[dict[str, Any]], topic: str) -> list[dict[str, Any]]:
    """Collapse multiple generated goals into one comprehensive master roadmap."""
    if not goals:
        return goals
    if len(goals) == 1:
        return goals

    def merge_unique(items: list[str], incoming: list[str], limit: int) -> list[str]:
        seen = {x.lower(): 1 for x in items}
        for val in incoming:
            key = val.lower()
            if key in seen:
                continue
            items.append(val)
            seen[key] = 1
            if len(items) >= limit:
                break
        return items

    primary = dict(goals[0])
    title = str(primary.get("title") or "").strip() or f"Master Plan: {topic}"
    primary["title"] = f"Master Plan: {topic}" if not title.lower().startswith("master plan:") else title
    primary["description"] = (
        f"Comprehensive consolidated roadmap for {topic}. "
        "This plan merges all generated sub-roadmaps into one detailed execution track."
    )
    primary["priority"] = max(int(g.get("priority") or 3) for g in goals)
    primary["difficulty"] = min(10, max(int(g.get("difficulty") or 5) for g in goals))
    primary["time_commitment_hours"] = round(sum(float(g.get("time_commitment_hours") or 0) for g in goals), 1)

    roadmap: list[str] = []
    instructions: list[str] = []
    prerequisites: list[str] = []
    shopping: list[str] = []
    context: list[str] = []
    daily: list[str] = []
    fit: list[str] = []
    subgoals: list[dict[str, Any]] = []

    for g in goals:
        roadmap = merge_unique(roadmap, _to_string_list(g.get("roadmap"), 28), 28)
        instructions = merge_unique(instructions, _to_string_list(g.get("instruction_steps"), 30), 30)
        prerequisites = merge_unique(prerequisites, _to_string_list(g.get("prerequisites"), 14), 14)
        shopping = merge_unique(shopping, _to_string_list(g.get("shopping_list"), 20), 20)
        context = merge_unique(context, _to_string_list(g.get("context_notes"), 14), 14)
        daily = merge_unique(daily, _to_string_list(g.get("daily_plan"), 28), 28)
        fit = merge_unique(fit, _to_string_list(g.get("schedule_fit_notes"), 14), 14)
        for sg in (g.get("subgoals") if isinstance(g.get("subgoals"), list) else []):
            if not isinstance(sg, dict):
                continue
            sg_title = str(sg.get("title") or "").strip()
            if not sg_title:
                continue
            subgoals.append({
                "title": sg_title,
                "description": str(sg.get("description") or "").strip(),
                "time_commitment_hours": max(0, float(sg.get("time_commitment_hours") or 0)),
                "target_date_hint": str(sg.get("target_date_hint") or "").strip(),
                "roadmap": _to_string_list(sg.get("roadmap"), 14),
                "instruction_steps": _to_string_list(sg.get("instruction_steps"), 16),
                "daily_plan": _to_string_list(sg.get("daily_plan"), 10),
            })

    primary["roadmap"] = roadmap
    primary["instruction_steps"] = instructions
    primary["prerequisites"] = prerequisites
    primary["shopping_list"] = shopping
    primary["context_notes"] = context
    primary["daily_plan"] = daily
    primary["schedule_fit_notes"] = fit
    if subgoals:
        primary["subgoals"] = subgoals[:14]
    return [primary]


def research_and_create_goals(
    topic: str,
    life_area_name: str | None = None,
    schedule_context: list[dict[str, Any]] | None = None,
    token_limit: int = 2000,
) -> dict[str, Any]:
    """Search the web for a topic, feed results to AI, and return goal suggestions.

    Returns {mode, search_results, analysis, goals[]}.
    Each goal includes strategy metadata for execution:
    {title, description, priority, difficulty, time_commitment_hours, target_date_hint,
        roadmap[], instruction_steps[], prerequisites[], shopping_list[], context_notes[],
        daily_plan[], schedule_fit_notes[]}.
    """
    clean_topic = _extract_topic(topic)
    raw_query = str(topic or "").strip()
    if not clean_topic or clean_topic == "Research Topic":
        return {"mode": "heuristic", "search_results": [], "analysis": "Please provide a research topic.", "goals": []}

    # Use the raw query for web search (more context = better results),
    # but use clean_topic for display and goal titles.
    search_query = raw_query if raw_query else clean_topic

    # Step 1: Web search
    search_results = web_search(search_query, num_results=6)

    # Build research context from search results
    if search_results:
        research_text = "\n\n".join(
            f"[{i+1}] {r['title']}\n{r['snippet']}\nURL: {r['link']}"
            for i, r in enumerate(search_results)
        )
    else:
        research_text = "(No web search results available — Tavily API may not be configured. Rely on your own knowledge.)"

    # Step 2: AI analysis + goal generation
    system_prompt = (
        "You are a life optimization research assistant. "
        "The user wants to research a topic and create actionable goals from the findings. "
        "Analyze the provided web search results, synthesize key insights, and propose concrete goals. "
        "All generated content must be specific to the exact research topic, not generic templates. "
        "Use domain-specific terminology, techniques, tools, and milestones from the supplied search evidence. "
        "Return valid JSON with keys:\n"
        '  "analysis": string — 2-4 paragraph summary of what you found and key takeaways\n'
        '  "goals": array of objects, each with:\n'
        '    "title": string — concise goal name\n'
        '    "description": string — actionable description with specific steps or milestones\n'
        '    "priority": integer 1-5 (5=highest)\n'
        '    "difficulty": integer 1-10\n'
        '    "time_commitment_hours": number — estimated total hours\n'
        '    "target_date_hint": string — relative timeline like "2 weeks", "1 month", "3 months"\n'
        '    "roadmap": array of 3-6 concrete milestone steps\n'
        '    "instruction_steps": array of specific instructions to execute this goal\n'
        '    "prerequisites": array of prerequisite knowledge/dependencies\n'
        '    "shopping_list": array of required tools/materials (empty array if none)\n'
        '    "context_notes": array of caveats/tips/constraints important for this topic\n'
        '    "daily_plan": array of 5-7 entries in day-by-day hour-by-hour format (example: "Monday 7:00 PM - 8:00 PM: knife drills")\n'
        '    "schedule_fit_notes": array describing how this goal fits around the existing daily schedule and what to adjust if conflicts occur\n'
        '    "subgoals": array of 4-12 detailed subgoal objects, each with title, description, roadmap[], instruction_steps[], daily_plan[], time_commitment_hours, target_date_hint\n'
        "Return exactly 1 goal object with a single comprehensive detailed roadmap, not multiple separate goal roadmaps."
    )

    area_note = f"\nTarget life area: {life_area_name}" if life_area_name else ""

    user_prompt = json.dumps({
        "research_topic": clean_topic,
        "search_results": research_text,
        "life_area": life_area_name or "General",
        "schedule_context": schedule_context or [],
        "instructions": f"Research this topic and create actionable goals.{area_note}",
    }, ensure_ascii=True)

    effective_limit = _sanitize_token_limit(token_limit, default=2000)
    provider, llm_result = _call_ai_json(system_prompt, user_prompt, max_tokens=effective_limit)

    if llm_result and isinstance(llm_result, dict):
        analysis = str(llm_result.get("analysis") or "").strip()
        raw_goals = llm_result.get("goals") if isinstance(llm_result.get("goals"), list) else []
        goals = []
        for i, g in enumerate(raw_goals):
            if not isinstance(g, dict):
                continue
            normalized = _normalize_research_goal(
                g,
                clean_topic,
                life_area_name=life_area_name,
                schedule_context=schedule_context,
                seed=i,
            )
            if normalized:
                goals.append(normalized)
        goals = _consolidate_research_goals(goals, clean_topic)
        if analysis or goals:
            return {
                "mode": provider,
                "search_results": search_results,
                "analysis": analysis or "Research complete.",
                "goals": goals,
            }

    # Heuristic fallback
    fallback_goals = _heuristic_research_goals(
        clean_topic,
        search_results,
        life_area_name=life_area_name,
        schedule_context=schedule_context,
    )
    if search_results:
        analysis = f"Found {len(search_results)} results for \"{clean_topic}\":\n\n"
        for i, r in enumerate(search_results):
            analysis += f"{i+1}. **{r['title']}** — {r['snippet']}\n"
        analysis += "\nGenerated a structured execution plan from these findings, including roadmap steps, prerequisites, and context notes."
    else:
        analysis = (
            "Generated a structured execution plan from the topic directly, including roadmap steps, prerequisites, "
            "and context notes."
        )

    return {
        "mode": "heuristic",
        "search_results": search_results,
        "analysis": analysis,
        "goals": fallback_goals,
    }


# ── Goal Analysis ──────────────────────────────────────────────────────────────

def _heuristic_analyze_goals(goals: list[dict[str, Any]]) -> dict[str, Any]:
    """Fallback heuristic analysis when no AI provider is available."""
    from datetime import date as _date
    today = _date.today()
    analyzed = []
    for g in goals:
        priority = int(g.get("priority") or 0)
        has_desc = bool((g.get("description") or "").strip())
        area = (g.get("area_name") or "").lower()
        target = (g.get("target_date") or "").strip()

        difficulty = [3, 5, 7][min(priority, 2)] + (1 if has_desc else 0)

        time_map = {
            "career": 200, "academic": 150, "fitness": 100,
            "finance": 80, "hobbies": 50, "appearance": 30,
        }
        time_hours = next((v for k, v in time_map.items() if k in area), 100)

        price_map = {
            "career": 500, "academic": 2000, "fitness": 300,
            "finance": 100, "hobbies": 200, "appearance": 400,
        }
        price = next((v for k, v in price_map.items() if k in area), 200)

        urgency = 0
        if target:
            try:
                t = _date.fromisoformat(target)
                days_left = (t - today).days
                if days_left < 30:
                    urgency = 30
                elif days_left < 90:
                    urgency = 15
                elif days_left < 180:
                    urgency = 5
            except ValueError:
                pass

        base_score = priority * 20 + 30
        priority_score = min(100, base_score + urgency)
        label = ["Low", "Medium", "High"][min(priority, 2)]
        analyzed.append({
            "id": g["id"],
            "difficulty": difficulty,
            "time_commitment_hours": time_hours,
            "price_estimate": price,
            "priority_score": priority_score,
            "reasoning": (
                f"{label}-priority {area or 'general'} goal; "
                "estimate based on life-area norms (configure an AI key for deeper analysis)."
            ),
        })

    sorted_goals = sorted(analyzed, key=lambda x: -x["priority_score"])
    return {
        "mode": "heuristic",
        "goals": analyzed,
        "priority_list": [x["id"] for x in sorted_goals],
        "summary": (
            f"Heuristic analysis of {len(goals)} active goal(s). "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY for AI-powered insights."
        ),
    }


def analyze_goals(goals: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze goals and return per-goal difficulty / time / cost scores plus a priority ranking."""
    if not goals:
        return {
            "mode": "heuristic",
            "goals": [],
            "priority_list": [],
            "summary": "No active goals to analyze.",
        }

    system_prompt = (
        "You are a life coach and strategic planner. "
        "Analyze each personal goal and assess: "
        "difficulty (integer 1-10, 1=trivial, 10=extremely hard), "
        "time_commitment_hours (total estimated hours to achieve, number), "
        "price_estimate (estimated USD cost to achieve, 0 if free), "
        "priority_score (integer 1-100 reflecting urgency × impact × feasibility), "
        "reasoning (one concise sentence). "
        "Then supply a top-level priority_list of goal IDs in recommended tackle order (highest impact first) "
        "and a summary paragraph. "
        "Return JSON with keys: goals (array of objects with id, difficulty, time_commitment_hours, "
        "price_estimate, priority_score, reasoning), priority_list (array of ints), summary (string)."
    )
    user_prompt = json.dumps(
        {
            "today": datetime.utcnow().strftime("%Y-%m-%d"),
            "goals": [
                {
                    "id": g.get("id"),
                    "title": g.get("title"),
                    "description": g.get("description") or "",
                    "life_area": g.get("area_name") or "",
                    "priority": g.get("priority"),
                    "target_date": g.get("target_date") or "",
                }
                for g in goals
            ],
        },
        ensure_ascii=True,
    )

    provider, result = _call_ai_json(system_prompt, user_prompt, max_tokens=2048)

    if result and isinstance(result.get("goals"), list):
        clean_goals = []
        for item in result.get("goals", []):
            if not isinstance(item, dict) or "id" not in item:
                continue
            try:
                clean_goals.append(
                    {
                        "id": int(item["id"]),
                        "difficulty": max(1, min(10, int(item.get("difficulty") or 5))),
                        "time_commitment_hours": float(item.get("time_commitment_hours") or 10),
                        "price_estimate": float(item.get("price_estimate") or 0),
                        "priority_score": max(1, min(100, int(item.get("priority_score") or 50))),
                        "reasoning": str(item.get("reasoning") or ""),
                    }
                )
            except (TypeError, ValueError):
                continue

        priority_list: list[int] = []
        if isinstance(result.get("priority_list"), list):
            for pid in result["priority_list"]:
                try:
                    priority_list.append(int(pid))
                except (TypeError, ValueError):
                    pass
        if not priority_list:
            priority_list = [x["id"] for x in sorted(clean_goals, key=lambda x: -x["priority_score"])]

        return {
            "mode": provider,
            "goals": clean_goals,
            "priority_list": priority_list,
            "summary": str(result.get("summary") or "AI analysis complete."),
        }

    return _heuristic_analyze_goals(goals)


def _estimate_candidate_minutes(item: dict[str, Any]) -> int:
    hours = item.get("time_commitment_hours")
    try:
        if hours is not None:
            h = float(hours)
            if h > 0:
                # Suggest a practical single-session slice, not total project hours.
                return max(25, min(120, int(round((h * 60) / 20))))
    except (TypeError, ValueError):
        pass

    kind = str(item.get("item_kind") or "").lower()
    if kind == "task":
        return 35
    if kind == "long_term_objective":
        return 50

    difficulty = int(item.get("difficulty") or 0)
    if difficulty >= 8:
        return 75
    if difficulty >= 5:
        return 55
    if difficulty >= 3:
        return 40
    return 30


def _score_today_candidate(item: dict[str, Any], today_iso: str) -> float:
    ai_score = item.get("ai_priority_score")
    try:
        ai_val = float(ai_score)
    except (TypeError, ValueError):
        ai_val = 0.0

    priority = int(item.get("priority") or 0)
    difficulty = int(item.get("difficulty") or 0)
    target = str(item.get("target_date") or "")[:10]

    due_boost = 0.0
    if target:
        if target < today_iso:
            due_boost = 35.0
        elif target == today_iso:
            due_boost = 28.0
        else:
            due_boost = 8.0

    base = ai_val if ai_val > 0 else (priority * 30 + due_boost)
    return base - (difficulty * 1.2)


def _heuristic_build_today_plan(
    schedule_tasks: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    now_iso: str,
    end_hour: int,
) -> dict[str, Any]:
    now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime.utcnow()
    now_min = now_dt.hour * 60 + now_dt.minute
    day_end = max(now_min + 30, min(24 * 60, int(end_hour) * 60))
    today_iso = now_dt.strftime("%Y-%m-%d")

    occupied: list[tuple[int, int]] = []
    for t in schedule_tasks:
        start = _parse_time_to_minutes(str(t.get("task_time") or ""))
        if start is None:
            continue
        duration = _default_duration_for_task(t)
        end = min(day_end, start + duration)
        if end <= now_min:
            continue
        occupied.append((max(now_min, start), end))

    occupied.sort(key=lambda x: x[0])
    merged: list[list[int]] = []
    for start, end in occupied:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    free_slots: list[dict[str, int]] = []
    cursor = now_min
    for start, end in merged:
        if start > cursor:
            free_slots.append({"start": cursor, "end": start})
        cursor = max(cursor, end)
    if cursor < day_end:
        free_slots.append({"start": cursor, "end": day_end})

    total_free = sum(max(0, s["end"] - s["start"]) for s in free_slots)

    ranked = []
    for c in candidates:
        if int(c.get("is_completed") or 0):
            continue
        minutes = _estimate_candidate_minutes(c)
        score = _score_today_candidate(c, today_iso)
        ranked.append({**c, "session_minutes": minutes, "score": score})

    ranked.sort(key=lambda x: (-x["score"], x["session_minutes"], str(x.get("title") or "").lower()))

    slots = [{"start": s["start"], "end": s["end"]} for s in free_slots]

    def allocate(minutes: int) -> tuple[int, int] | None:
        for slot in slots:
            cap = slot["end"] - slot["start"]
            if cap >= minutes:
                out = (slot["start"], slot["start"] + minutes)
                slot["start"] += minutes
                return out
        return None

    recommendations: list[dict[str, Any]] = []
    for cand in ranked:
        allocation = allocate(int(cand["session_minutes"]))
        if not allocation:
            continue
        start_min, end_min = allocation
        recommendations.append(
            {
                "archive_id": str(cand.get("archive_id") or ""),
                "source_type": str(cand.get("source_type") or ""),
                "item_kind": str(cand.get("item_kind") or ""),
                "id": cand.get("id"),
                "title": str(cand.get("title") or ""),
                "description": cand.get("description"),
                "area_name": str(cand.get("area_name") or ""),
                "target_date": cand.get("target_date"),
                "section_key": cand.get("section_key"),
                "planned_start": _minutes_to_12h(start_min),
                "planned_end": _minutes_to_12h(end_min),
                "planned_minutes": int(cand["session_minutes"]),
                "score": round(float(cand["score"]), 1),
                "reason": "Best fit for available time and priority.",
                "ai_reasoning": str(cand.get("ai_reasoning") or ""),
            }
        )
        if len(recommendations) >= 6:
            break

    return {
        "mode": "heuristic",
        "summary": f"Planned {len(recommendations)} focus block(s) in {total_free} free minute(s).",
        "free_minutes": total_free,
        "recommendations": recommendations,
    }


def build_today_plan(
    schedule_tasks: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    now_iso: str,
    end_hour: int = 22,
) -> dict[str, Any]:
    """Build a today plan combining schedule occupancy and archive candidates."""
    heuristic = _heuristic_build_today_plan(schedule_tasks, candidates, now_iso, end_hour)

    provider, result = _call_ai_json(
        system_prompt=(
            "You are a daily planning assistant. Given fixed scheduled tasks and candidate goals/tasks, "
            "select the best candidates that fit into today's free windows. "
            "Return JSON with keys: summary (string), recommendations (array). "
            "Each recommendation must include: archive_id, reason. "
            "Optional: planned_start (H:MM AM/PM), planned_end (H:MM AM/PM), planned_minutes (int)."
        ),
        user_prompt=json.dumps(
            {
                "now_iso": now_iso,
                "end_hour": end_hour,
                "scheduled": [
                    {
                        "id": t.get("id"),
                        "title": t.get("name") or t.get("title"),
                        "task_time": t.get("task_time"),
                        "subgroup": t.get("subgroup"),
                    }
                    for t in schedule_tasks
                ],
                "candidates": [
                    {
                        "archive_id": c.get("archive_id"),
                        "id": c.get("id"),
                        "title": c.get("title"),
                        "source_type": c.get("source_type"),
                        "item_kind": c.get("item_kind"),
                        "priority": c.get("priority"),
                        "difficulty": c.get("difficulty"),
                        "target_date": c.get("target_date"),
                        "ai_priority_score": c.get("ai_priority_score"),
                        "estimated_minutes": _estimate_candidate_minutes(c),
                    }
                    for c in candidates
                    if not int(c.get("is_completed") or 0)
                ],
                "fallback_heuristic": heuristic,
            },
            ensure_ascii=True,
        ),
        max_tokens=1800,
    )

    if result and isinstance(result.get("recommendations"), list):
        by_archive_id = {str(c.get("archive_id") or ""): c for c in candidates}
        clean_recs: list[dict[str, Any]] = []
        for rec in result.get("recommendations", []):
            if not isinstance(rec, dict):
                continue
            aid = str(rec.get("archive_id") or "")
            if not aid or aid not in by_archive_id:
                continue
            src = by_archive_id[aid]
            minutes = rec.get("planned_minutes")
            try:
                minutes_val = int(minutes) if minutes is not None else _estimate_candidate_minutes(src)
            except (TypeError, ValueError):
                minutes_val = _estimate_candidate_minutes(src)
            clean_recs.append(
                {
                    "archive_id": aid,
                    "source_type": str(src.get("source_type") or ""),
                    "item_kind": str(src.get("item_kind") or ""),
                    "id": src.get("id"),
                    "title": str(src.get("title") or ""),
                    "description": src.get("description"),
                    "area_name": str(src.get("area_name") or ""),
                    "target_date": src.get("target_date"),
                    "section_key": src.get("section_key"),
                    "planned_start": rec.get("planned_start"),
                    "planned_end": rec.get("planned_end"),
                    "planned_minutes": max(15, min(180, minutes_val)),
                    "score": _score_today_candidate(src, datetime.utcnow().strftime("%Y-%m-%d")),
                    "reason": str(rec.get("reason") or "AI selected this as a strong fit for today."),
                    "ai_reasoning": str(src.get("ai_reasoning") or ""),
                }
            )
        if clean_recs:
            return {
                "mode": provider,
                "summary": str(result.get("summary") or f"AI selected {len(clean_recs)} item(s) for today."),
                "free_minutes": heuristic.get("free_minutes", 0),
                "recommendations": clean_recs,
            }

    return heuristic


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
