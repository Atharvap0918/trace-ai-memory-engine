"""Presentation-only formatting for memory records.

Stored memory content, evidence, provenance, IDs, and version history are never
changed here. This module creates safe, compact fields for the dashboard while
leaving the original database rows intact for inspection and export.
"""
from __future__ import annotations

import json
import re
from typing import Any


_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.I,
)
_HEX_ID = re.compile(r"\b[0-9a-f]{20,64}\b", re.I)
_EPISODE_PREFIX = re.compile(r"^\s*meaningful episode from this conversation\s*:\s*", re.I)
_SEGMENT = re.compile(
    r"(?P<label>objective|unresolved_question|decision|reason|rejected_alternative|"
    r"constraint|lesson|milestone|assistant_proposal|pending_suggestion)\s*"
    r"(?:\(\s*(?P<role>user|assistant)\s*(?:[;,:]\s*)?message\s+[^)]*\)|"
    r"\(\s*(?P<role2>user|assistant)[^)]*\))?\s*:\s*",
    re.I,
)
_LABELS = {
    "objective": "Conversation summary",
    "unresolved_question": "Unresolved question",
    "decision": "Decision",
    "reason": "Reason",
    "rejected_alternative": "Rejected alternative",
    "constraint": "Constraint",
    "lesson": "Lesson",
    "milestone": "Milestone",
    "assistant_proposal": "Pending suggestion",
    "pending_suggestion": "Pending suggestion",
}
_SUMMARY_LABELS = {
    "objective": "focused on",
    "decision": "reached a decision about",
    "reason": "explained",
    "milestone": "recorded a milestone for",
    "lesson": "captured a lesson about",
}
_INTERNAL_FIELD = re.compile(
    r"\b(?:memory_id|message_id|conversation_id|source_id|experience_id|"
    r"assistant_message_id|user_id|created_at|updated_at|source_type|"
    r"memory_layer|memory_type|slot)\s*[:=]\s*[^,;\n}]+",
    re.I,
)
_ROLE_MESSAGE = re.compile(
    r"\b(?:user|assistant)\s*[:;,-]?\s*message\s*[^\s,;:)\]}]+\s*\)?",
    re.I,
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _truncate(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", _as_text(value)).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]) + "…"


def _sentence(value: Any) -> str:
    text = _as_text(value).strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _clean_fragment(value: Any) -> str:
    """Remove implementation markers while retaining human-authored meaning."""
    text = _as_text(value)
    text = _ROLE_MESSAGE.sub("", text)
    text = _INTERNAL_FIELD.sub("", text)
    text = _UUID.sub("", text)
    text = _HEX_ID.sub("", text)
    text = re.sub(r"\b(?:assistant[_ ]proposal|pending[_ ]suggestion)\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:unresolved[_ ]question)\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n:;,|()[]{}")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([.!?])(?:\s*[.!?])+", r"\1", text)
    return text


def _json_segments(text: str) -> list[dict[str, str]]:
    """Read structured episode-like JSON without showing its field names."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, dict):
        return []
    aliases = {
        "objective": "objective",
        "summary": "objective",
        "conversation_summary": "objective",
        "unresolved_question": "unresolved_question",
        "question": "unresolved_question",
        "assistant_proposal": "assistant_proposal",
        "pending_suggestion": "assistant_proposal",
        "decision": "decision",
        "reason": "reason",
        "rejected_alternative": "rejected_alternative",
        "lesson": "lesson",
        "milestone": "milestone",
        "constraint": "constraint",
    }
    segments = []
    for key, value in value.items():
        kind = aliases.get(str(key).lower())
        if kind is None:
            continue
        if isinstance(value, list):
            values = value
        else:
            values = [value]
        for item in values:
            cleaned = _clean_fragment(item)
            if cleaned:
                segments.append({"kind": kind, "text": cleaned})
    return segments


def _json_human_text(text: str) -> str:
    """Flatten safe human text from JSON without exposing keys or identifiers."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return ""
    if not isinstance(value, (dict, list)):
        return ""
    preferred = []
    ignored = re.compile(r"(?:^|_)(?:id|uuid|message|conversation|source|created|updated|timestamp)(?:$|_)", re.I)

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                if ignored.search(str(child_key)):
                    continue
                walk(child, str(child_key).lower())
        elif isinstance(node, list):
            for child in node:
                walk(child, key)
        elif isinstance(node, str) and node.strip():
            label = {
                "user_statement": "Conversation summary",
                "assistant_response": "Response",
                "summary": "Summary",
                "content": "Details",
                "text": "Details",
            }.get(key, "Details")
            preferred.append(f"{label}: {_clean_fragment(node)}")

    walk(value)
    return " ".join(dict.fromkeys(x for x in preferred if x.split(": ", 1)[-1]))


def _segments(text: str) -> list[dict[str, str]]:
    parsed = _json_segments(text)
    if parsed:
        return parsed
    text = _EPISODE_PREFIX.sub("", _as_text(text))
    matches = list(_SEGMENT.finditer(text))
    if not matches:
        return []
    result = []
    for index, match in enumerate(matches):
        body = text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        cleaned = _clean_fragment(body)
        if cleaned:
            result.append({"kind": match.group("label").lower(), "text": cleaned})
    return result


def _unique_segments(segments: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    result = []
    seen = set()
    for segment in segments:
        text = _truncate(segment.get("text"), 240)
        key = (segment.get("kind"), text.casefold())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append({"kind": segment.get("kind", "detail"), "text": text})
        if len(result) >= limit:
            break
    return result


# ---------------------------------------------------------------------------
# Episodic presentation: one-line card summary + structured detail sections.
# Presentation only: stored content, evidence and provenance are never changed.
# ---------------------------------------------------------------------------
_KIND_ORDER = ("objective", "decision", "rejected_alternative", "constraint",
               "unresolved_question", "assistant_proposal")
_SECTION_TITLES = {
    "objective": "Objective",
    "decision": "Decisions",
    "rejected_alternative": "Rejected alternatives",
    "constraint": "Constraints",
    "unresolved_question": "Unresolved questions",
    "assistant_proposal": "Assistant suggestions (not confirmed)",
}
_EVENT_LABELS = {
    "objective": "Objective stated",
    "decision": "Decision made",
    "rejected_alternative": "Alternative rejected",
    "constraint": "Constraint noted",
    "unresolved_question": "Question left open",
    "assistant_proposal": "Assistant suggested",
    "reason": "Reason given",
    "lesson": "Lesson noted",
    "milestone": "Milestone reached",
}
_REQUEST_PREFIX = re.compile(
    r"^\s*(?:(?:please|hey|hi|hello)[,\s]+)?(?:(?:i|we)\s+(?:really\s+)?(?:want|need|would like|wish|am trying|'m trying)\s+(?:you\s+)?(?:to\s+)?"
    r"|(?:i\s+am|i[\u2019']m|we\s+are|we[\u2019']re)\s+|(?:i|we)\s+(?:have\s+)?decided\s+(?:to\s+)?|(?:can|could|will|would)\s+you\s+(?:please\s+)?|help me (?:to\s+)?|i need help (?:with|on|in)\s+)",
    re.I,
)
_CLAUSE_CUT = re.compile(r"\s+(?:which|that|where|who|and (?:i|we)|so (?:that|i|we)|because|but)\b|[,;:\u2014\u2013]|\s--\s", re.I)
_ABOUT = re.compile(r"\b(?:the|this|my|a|an)\s+([a-z][\w -]{1,30}?)\s+(?:is|are|was)\s+about\s+(.+?)(?:[.!?]|$)", re.I)
_PRONOUNS = ((r"\bmyself\b", "themselves"), (r"\bmy\b", "their"), (r"\bme\b", "them"), (r"\bi am\b", "they are"), (r"\bi'm\b", "they are"), (r"\bi\b", "they"), (r"\bour\b", "their"), (r"\bwe\b", "they"))


def _words(text: str) -> list[str]:
    return text.split()


_DANGLING = {"and", "or", "with", "for", "to", "the", "a", "an", "of", "using", "in", "on", "at", "by", "from", "as", "is", "are"}


def _cap_words(text: str, limit: int) -> str:
    words = _words(text)[:limit]
    while words and (words[-1].lower().strip(" ,;:-") in _DANGLING or not words[-1].strip(" ,;:-")):
        words.pop()
    return " ".join(words).rstrip(" ,;:-")


def _neutral(text: str) -> str:
    for pattern, repl in _PRONOUNS:
        text = re.sub(pattern, repl, text, flags=re.I)
    return text


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _topic(primary: str, request: bool = True) -> str:
    """Short, human noun/verb phrase describing what the episode was about."""
    text = _clean_fragment(primary)
    if text.endswith("?"):
        return _cap_words(text.rstrip("?"), 14) + "?"
    about = _ABOUT.search(text)
    if about:
        noun = _neutral(about.group(1).strip())
        rest = _neutral(about.group(2).strip())
        return "the " + _cap_words(f"{noun} about {rest}", 12)
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    stripped = _REQUEST_PREFIX.sub("", first).strip()
    if stripped != first.strip():
        head = _CLAUSE_CUT.split(stripped, maxsplit=1)[0].strip()
        if re.match(r"[a-z]+ing\b", head, re.I):
            return _cap_words(_neutral(_lower_first(head)), 11)
        return ("a request to " if request else "") + _cap_words(_neutral(_lower_first(head)), 10)
    head = _CLAUSE_CUT.split(first, maxsplit=1)[0].strip()
    return _cap_words(_neutral(_lower_first(head)), 12)


def _card_summary(groups: dict[str, list[str]]) -> str:
    """One sentence, ~10-20 words, free of IDs and internal labels."""
    primary = (groups.get("objective") or groups.get("decision") or groups.get("unresolved_question")
               or groups.get("rejected_alternative") or groups.get("constraint") or groups.get("assistant_proposal") or [""])[0]
    topic = _topic(primary, request=bool(groups.get("objective"))) if primary else ""
    decisions = len(groups.get("decision", []))
    questions = len(groups.get("unresolved_question", []))
    extras = []
    if decisions and groups.get("objective"):
        extras.append(_plural(decisions, "decision"))
    if questions and groups.get("objective"):
        extras.append(_plural(questions, "open question"))
    if groups.get("assistant_proposal") and not extras and groups.get("objective"):
        extras.append("pending suggestions")
    if not topic:
        return "Conversation episode with saved context."
    if groups.get("objective"):
        lead = "Discussion of " if topic.startswith("the ") else "Conversation about "
    elif groups.get("decision"):
        lead = "Decision made: "
    elif groups.get("unresolved_question"):
        lead = "Open question: "
    else:
        lead = "Conversation covering "
    sentence = lead + (topic[:1].lower() + topic[1:] if lead.endswith(("of ", "about ", "covering ")) and not topic.endswith("?") else topic)
    if extras:
        sentence += f", with {' and '.join(extras)}"
    sentence = _cap_words(sentence, 20)
    sentence = sentence[:1].upper() + sentence[1:]
    return sentence if sentence.endswith((".", "!", "?")) else sentence + "."


def _layout_text(value: Any) -> str:
    """Remove internal markers but keep line breaks so long text stays readable."""
    text = _as_text(value)
    text = _ROLE_MESSAGE.sub("", text)
    text = _INTERNAL_FIELD.sub("", text)
    text = _UUID.sub("", text)
    text = _HEX_ID.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _episode_items(content: Any, items: Any = None) -> list[dict[str, Any]]:
    """Prefer the stored structured items; fall back to parsing the summary text."""
    parsed = []
    if items:
        try:
            data = json.loads(items) if isinstance(items, str) else items
        except (TypeError, ValueError):
            data = []
        for it in data if isinstance(data, list) else []:
            if isinstance(it, dict) and it.get("text"):
                parsed.append({"kind": str(it.get("kind") or "detail").lower(), "role": it.get("role") or "",
                               "text": _layout_text(it["text"]), "created_at": it.get("created_at") or ""})
    if not parsed:
        for seg in _segments(_as_text(content)):
            text = _layout_text(seg["text"]) if False else seg["text"]
            parsed.append({"kind": seg["kind"], "role": "assistant" if seg["kind"] in ("assistant_proposal", "pending_suggestion") else "user",
                           "text": text, "created_at": ""})
    for it in parsed:
        if it["kind"] == "pending_suggestion":
            it["kind"] = "assistant_proposal"
    return parsed


def episode_view(content: Any, items: Any = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build card summary + detail sections for an episodic memory."""
    events = _episode_items(content, items)
    groups: dict[str, list[str]] = {}
    for ev in events:
        groups.setdefault(ev["kind"], []).append(_clean_fragment(ev["text"]) if ev["kind"] != "assistant_proposal" else ev["text"])
    if not events:
        fallback = _clean_fragment(_EPISODE_PREFIX.sub("", _as_text(content)))
        return {"summary": _card_summary({"objective": [fallback]}) if fallback else "Conversation episode with saved context.",
                "overview": fallback[:600], "sections": [], "timeline": [], "source": source or {}}
    summary = _card_summary(groups)
    sections = []
    for kind in _KIND_ORDER:
        entries = [e for e in events if e["kind"] == kind]
        if entries:
            sections.append({"kind": kind, "title": _SECTION_TITLES[kind],
                             "items": [{"text": e["text"], "role": e["role"], "when": e["created_at"]} for e in entries]})
    timeline = [{"label": _EVENT_LABELS.get(e["kind"], "Event"), "kind": e["kind"], "role": e["role"],
                 "text": _truncate(e["text"], 160), "when": e["created_at"]}
                for e in sorted(events, key=lambda e: e["created_at"] or "")]
    counts = {k: len([e for e in events if e["kind"] == k]) for k in _KIND_ORDER}
    overview_parts = [f"This episode records {len(events)} key moment" + ("" if len(events) == 1 else "s") + " from the conversation"]
    bits = [f"{_plural(n, label)}" for k, label in (("decision", "decision"), ("unresolved_question", "unresolved question"),
            ("assistant_proposal", "assistant suggestion"), ("rejected_alternative", "rejected alternative")) if (n := counts.get(k))]
    if bits:
        overview_parts.append(": " + ", ".join(bits))
    return {"summary": summary, "overview": "".join(overview_parts) + ".", "sections": sections,
            "timeline": timeline, "counts": counts, "source": source or {}}


def _episodic_presentation(content: Any) -> tuple[str, list[dict[str, str]]]:
    return episode_view(content)["summary"], []


def _legacy_episodic_presentation(content: Any) -> tuple[str, list[dict[str, str]]]:
    raw = _as_text(content)
    segments = _unique_segments(_segments(raw))
    if not segments:
        fallback = _clean_fragment(raw)
        return (_truncate(fallback or "Conversation episode recorded.", 420), [])

    objective = next((s["text"] for s in segments if s["kind"] == "objective"), "")
    unresolved = [s["text"] for s in segments if s["kind"] == "unresolved_question"]
    decisions = [s["text"] for s in segments if s["kind"] == "decision"]
    suggestions = [s["text"] for s in segments if s["kind"] in ("assistant_proposal", "pending_suggestion")]
    rejected = [s["text"] for s in segments if s["kind"] == "rejected_alternative"]

    sentences = []
    if objective:
        sentences.append(f"The conversation focused on {_sentence(objective)}")
    elif decisions:
        sentences.append(f"The conversation reached a decision about {_sentence(decisions[0])}")
    elif unresolved:
        sentences.append(f"The conversation raised an unresolved question: {_sentence(unresolved[0])}")
    else:
        sentences.append(f"The conversation explored {_sentence(segments[0]['text'])}")
    if decisions and not objective:
        sentences.append(f"Decision: {_sentence(decisions[0])}")
    elif unresolved and objective:
        sentences.append(f"The main open question is {_sentence(unresolved[0])}")
    elif suggestions:
        sentences.append("A suggestion is pending user confirmation.")
    elif rejected:
        sentences.append(f"An alternative was ruled out: {_sentence(rejected[0])}")
    summary = _truncate(" ".join(sentences), 420)

    highlights = []
    for kind, values in (
        ("unresolved_question", unresolved),
        ("assistant_proposal", suggestions),
        ("decision", decisions),
        ("rejected_alternative", rejected),
    ):
        if values:
            highlights.append({"kind": kind, "label": _LABELS[kind], "text": _truncate(values[0], 160)})
    return summary, highlights[:2]


def clean_text(value: Any, memory_type: str = "", source_type: str = "", memory_layer: str = "") -> str:
    """Return bounded human-readable text for cards and inspection summaries."""
    if str(memory_layer).lower() == "episodic" or str(memory_type).lower() in ("episodic", "episode"):
        return _episodic_presentation(value)[0]
    text = _as_text(value)
    json_text = _json_human_text(text) if text.startswith(("{", "[")) else ""
    text = json_text or _clean_fragment(text)
    if source_type in ("ASSISTANT_SUGGESTION", "LLM_INFERENCE"):
        text = f"Pending suggestion: {text}" if text else "Pending suggestion awaiting user confirmation."
    return _truncate(text or "Memory details are available in the source evidence.", 420)


def display_memory(memory: dict[str, Any], episode_items: Any = None, source: dict[str, Any] | None = None, with_details: bool = False) -> dict[str, Any]:
    """Add presentation fields while returning the original values unchanged."""
    result = dict(memory)
    is_episode = str(memory.get("memory_layer", "")).lower() == "episodic" or str(memory.get("memory_type", "")).lower() in ("episodic", "episode")
    if is_episode:
        view = episode_view(memory.get("content"), episode_items, source)
        result["display_content"] = view["summary"]
        result["display_summary"] = view["summary"]
        result["display_sections"] = []
        result["is_episodic"] = True
        if with_details:
            result["episode"] = view
    else:
        result["display_content"] = clean_text(
            memory.get("content"),
            memory.get("memory_type", ""),
            memory.get("source_type", ""),
            memory.get("memory_layer", ""),
        )
        result["display_summary"] = result["display_content"]
        result["display_sections"] = []
    try:
        entities = json.loads(memory.get("entities") or "[]") if "entities" in memory else []
    except (TypeError, ValueError):
        entities = []
    result["display_label"] = short_label(memory, entities)
    return result


def short_label(memory: dict[str, Any], entities: list[dict[str, Any]] | None = None) -> str:
    entities = entities or []
    kind = str(memory.get("memory_type") or "Memory")
    slot = str(memory.get("slot") or "")
    content = str(memory.get("content") or "")
    is_episode = str(memory.get("memory_layer", "")).lower() == "episodic" or kind.lower() in ("episodic", "episode")
    if is_episode:
        summary, _ = _episodic_presentation(content)
        return _truncate("Conversation episode", 36) if summary else "Conversation episode"
    if memory.get("source_type") in ("ASSISTANT_SUGGESTION", "LLM_INFERENCE"):
        return "Pending suggestion"
    if kind.lower() == "project":
        project = re.search(r"\bproject called\s+([A-Z0-9][\w.-]*)", content, re.I)
        if project:
            return _truncate("Project · " + project.group(1), 36)
        if slot.startswith("stack:"):
            values = [str(e.get("value", "")).strip() for e in entities if e.get("value")]
            if values:
                return _truncate("Uses · " + ", ".join(values[:2]), 36)
            use = re.search(r"\buses?\s+(.+?)(?:[.!?]|$)", content, re.I)
            if use:
                return _truncate("Uses · " + use.group(1), 36)
        return "Project"
    return _truncate(kind, 36)
