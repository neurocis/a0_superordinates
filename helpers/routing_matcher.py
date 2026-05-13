"""Routing discovery matcher for A0 Superordinates.

The matcher keeps skill/role evidence as first priority and falls back to
agent/superordinate-name matching only when no skill-based candidate is found.
It returns a policy decision instead of blindly selecting ambiguous matches.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_OWNER_NAME = "A0"
AUTO_ROUTE_THRESHOLD = 0.75
CLEAR_MARGIN = 0.12
CLOSE_MARGIN = 0.12

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class MatchResult:
    """One scored routing candidate."""

    candidate: Mapping[str, Any]
    score: float
    match_type: str
    reason: str

    @property
    def name(self) -> str:
        return str(self.candidate.get("name") or self.candidate.get("label") or "")

    @property
    def ctxid(self) -> str:
        return str(self.candidate.get("ctxid") or self.candidate.get("id") or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ctxid": self.ctxid,
            "name": self.name,
            "score": self.score,
            "match_type": self.match_type,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RoutingDecision:
    """Routing policy result."""

    action: str
    selected: Mapping[str, Any] | None
    confidence: float
    match_type: str
    reason: str
    candidates: tuple[MatchResult, ...]
    prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "selected": dict(self.selected) if self.selected is not None else None,
            "confidence": self.confidence,
            "match_type": self.match_type,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "prompt": self.prompt,
        }


def normalize_text(value: Any) -> str:
    """Case-insensitive, punctuation/spacing tolerant text normalization."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(_WORD_RE.findall(text.lower()))


def normalized_compact(value: Any) -> str:
    """Normalize text and remove spaces for punctuation/spacing tolerant substring checks."""
    return normalize_text(value).replace(" ", "")


def tokens(value: Any) -> set[str]:
    return set(normalize_text(value).split())


def _candidate_name(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("name") or candidate.get("label") or "")


def _candidate_skill_text(candidate: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("skill", "skills", "role", "roles", "description", "summary"):
        value = candidate.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            parts.extend(str(item) for item in value)
    return "\n".join(parts)


def score_skill_match(query: str, candidate: Mapping[str, Any]) -> MatchResult | None:
    """Score skill/role evidence. Skill matches intentionally precede name matches."""
    query_norm = normalize_text(query)
    if not query_norm:
        return None

    skill_text = _candidate_skill_text(candidate)
    skill_norm = normalize_text(skill_text)
    if not skill_norm:
        return None

    query_terms = {term for term in query_norm.split() if len(term) >= 3}
    skill_terms = set(skill_norm.split())
    if not query_terms:
        return None

    if query_norm == skill_norm or query_norm in skill_norm:
        return MatchResult(candidate, 0.97, "skill", "query phrase matched candidate skill/role text")

    overlap = query_terms & skill_terms
    if not overlap:
        return None

    coverage = len(overlap) / max(len(query_terms), 1)
    if coverage < 0.5 and len(overlap) < 2:
        return None

    # Keep all skill matches above the name auto-route threshold, because the
    # policy tries skill evidence first and only falls back to names if none exist.
    score = min(0.95, 0.78 + (coverage * 0.17))
    return MatchResult(candidate, round(score, 4), "skill", f"skill/role token overlap: {', '.join(sorted(overlap))}")


def score_name_match(query: str, candidate: Mapping[str, Any]) -> MatchResult | None:
    """Score fallback name matches with exact > token > substring priority."""
    name = _candidate_name(candidate)
    query_norm = normalize_text(query)
    name_norm = normalize_text(name)
    if not query_norm or not name_norm:
        return None

    if query_norm == name_norm:
        return MatchResult(candidate, 1.0, "exact_name", "normalized exact agent/superordinate name match")

    query_tokens = set(query_norm.split())
    name_tokens = set(name_norm.split())
    if query_tokens and query_tokens <= name_tokens:
        return MatchResult(candidate, 0.86, "token_name", "query matched complete name token(s)")

    # Word-boundary partials such as "cal" -> "Cal Dev" are useful, but score
    # below complete-token matches so ambiguity policy can reject close results.
    if any(
        len(qt) >= 3 and any(nt.startswith(qt) for nt in name_tokens)
        for qt in query_tokens
    ):
        return MatchResult(candidate, 0.82, "token_name", "query matched name token boundary/prefix")

    query_compact = normalized_compact(query)
    name_compact = normalized_compact(name)
    if query_compact and (query_compact in name_compact or name_compact in query_compact):
        return MatchResult(candidate, 0.72, "substring_name", "normalized substring name match")

    return None


def _sorted_matches(matches: Sequence[MatchResult]) -> tuple[MatchResult, ...]:
    priority = {
        "skill": 4,
        "exact_name": 3,
        "token_name": 2,
        "substring_name": 1,
    }
    return tuple(
        sorted(
            matches,
            key=lambda match: (
                match.score,
                priority.get(match.match_type, 0),
                -len(match.name),
                match.name.lower(),
            ),
            reverse=True,
        )
    )


def _find_default_owner(candidates: Sequence[Mapping[str, Any]], default_owner: str) -> Mapping[str, Any] | None:
    wanted = normalize_text(default_owner)
    for candidate in candidates:
        if normalize_text(_candidate_name(candidate)) == wanted:
            return candidate
    for candidate in candidates:
        if normalized_compact(_candidate_name(candidate)) == normalized_compact(default_owner):
            return candidate
    return None


def build_ambiguity_prompt(query: str, candidates: Sequence[MatchResult]) -> str:
    """Prompt text returned when routing would be unsafe."""
    lines = [
        f"I found multiple possible superordinates for '{query}' and won't auto-route without confirmation.",
        "Please choose one target by name or ContextID:",
    ]
    for match in candidates:
        label = match.name or match.ctxid or "Unnamed"
        ctx = f" ({match.ctxid})" if match.ctxid else ""
        lines.append(f"- {label}{ctx} — {match.match_type}, confidence {match.score:.2f}")
    return "\n".join(lines)


def decide_route(
    query: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    default_owner: str = DEFAULT_OWNER_NAME,
    threshold: float = AUTO_ROUTE_THRESHOLD,
    clear_margin: float = CLEAR_MARGIN,
) -> RoutingDecision:
    """Decide whether/how to route a request.

    Policy:
    1. Try skill-based matches first.
    2. If no skill matches, fail over to name matching.
    3. Auto-route only when the top match clears the threshold and has a clear
       margin over the runner-up.
    4. Ask for disambiguation on close candidates.
    5. Route to the default owner (A0) if present; otherwise return no-match
       guidance.
    """
    candidate_list = list(candidates or [])
    skill_matches = _sorted_matches(
        [match for candidate in candidate_list if (match := score_skill_match(query, candidate))]
    )
    matches = skill_matches
    source = "skill"

    if not matches:
        matches = _sorted_matches(
            [match for candidate in candidate_list if (match := score_name_match(query, candidate))]
        )
        source = "name"

    if matches:
        top = matches[0]
        runner_up = matches[1] if len(matches) > 1 else None
        close = tuple(match for match in matches if top.score - match.score <= CLOSE_MARGIN)
        if len(close) > 1:
            return RoutingDecision(
                action="disambiguate",
                selected=None,
                confidence=top.score,
                match_type=top.match_type,
                reason="multiple close candidates; auto-routing suppressed",
                candidates=close,
                prompt=build_ambiguity_prompt(query, close),
            )

        runner_margin_ok = runner_up is None or (top.score - runner_up.score) >= clear_margin
        if top.score >= threshold and runner_margin_ok:
            return RoutingDecision(
                action="route",
                selected=top.candidate,
                confidence=top.score,
                match_type=top.match_type,
                reason=f"{source}-based match exceeded confidence threshold with clear margin",
                candidates=matches,
            )

        return RoutingDecision(
            action="disambiguate",
            selected=None,
            confidence=top.score,
            match_type=top.match_type,
            reason="top candidate did not clear confidence/margin policy",
            candidates=matches[:3],
            prompt=build_ambiguity_prompt(query, matches[:3]),
        )

    default = _find_default_owner(candidate_list, default_owner)
    if default is not None:
        return RoutingDecision(
            action="fallback",
            selected=default,
            confidence=0.5,
            match_type="default_owner",
            reason=f"no confident skill or name match; falling back to default owner {default_owner}",
            candidates=(),
        )

    return RoutingDecision(
        action="no_match",
        selected=None,
        confidence=0.0,
        match_type="none",
        reason=(
            "No confident skill or agent-name match found, and the default owner "
            f"{default_owner} was not available. Ask the user for a target superordinate/context."
        ),
        candidates=(),
    )
