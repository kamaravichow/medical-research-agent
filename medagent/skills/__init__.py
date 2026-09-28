"""Specialised skills: clinical playbooks the agent loads for the task at hand.

Each skill is a folder with a SKILL.md: YAML front matter (name, description,
triggers, entity_signals, tools) plus Markdown instructions, which is the same
layout Anthropic Agent Skills use. Skills are chosen per question by a
deterministic router that combines keyword triggers with entities found by the
clinical NER model. The chosen skills' instructions are injected into the
system prompt through LangChain middleware, and the agent can pull in any other
skill on demand with the `load_skill` tool (progressive disclosure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

LIBRARY = Path(__file__).parent / "library"


@dataclass
class Skill:
    name: str
    title: str
    description: str
    body: str
    triggers: list[re.Pattern[str]] = field(default_factory=list)
    entity_signals: list[str] = field(default_factory=list)
    min_entities: int = 1
    tools: list[str] = field(default_factory=list)
    path: Path | None = None

    def instructions(self) -> str:
        tools = f"\nPreferred tools: {', '.join(self.tools)}." if self.tools else ""
        return f"## Skill: {self.title}\n{self.body.strip()}{tools}"


@dataclass
class SkillMatch:
    skill: Skill
    score: float
    reasons: list[str]


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not match:
        raise ValueError(f"{path}: missing YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    for key in ("name", "description"):
        if not meta.get(key):
            raise ValueError(f"{path}: front matter needs '{key}'")
    return Skill(
        name=meta["name"],
        title=meta.get("title", meta["name"]),
        description=" ".join(str(meta["description"]).split()),
        body=match.group(2),
        triggers=[re.compile(t, re.I) for t in meta.get("triggers", [])],
        entity_signals=[s.upper() for s in meta.get("entity_signals", [])],
        min_entities=int(meta.get("min_entities", 1)),
        tools=list(meta.get("tools", [])),
        path=path,
    )


class SkillRegistry:
    def __init__(self, dirs: Iterable[Path] = (LIBRARY,)):
        self.skills: dict[str, Skill] = {}
        for d in dirs:
            for path in sorted(Path(d).glob("*/SKILL.md")):
                skill = parse_skill(path)
                self.skills[skill.name] = skill  # later dirs override the built-in library

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def index(self) -> str:
        return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

    def route(self, question: str, entity_labels: list[str] | None = None, limit: int = 3, threshold: float = 2.0) -> list[SkillMatch]:
        """Rank skills for a question. Each keyword trigger scores 2; NER entity signals add 1 (or 1.5 for a rich case)."""
        labels = [l.upper() for l in entity_labels or []]
        matches: list[SkillMatch] = []
        for skill in self.skills.values():
            score, reasons = 0.0, []
            for pattern in skill.triggers:
                m = pattern.search(question)
                if m:
                    score += 2
                    reasons.append(f"'{m.group(0)[:30]}'")
            hits = [l for l in labels if l in skill.entity_signals]
            if hits and len(hits) >= skill.min_entities:
                bonus = 1.5 if len(hits) >= 3 else 1.0
                score += bonus
                reasons.append(f"NER: {len(hits)} {'/'.join(sorted(set(hits))).lower()} entities")
            if score >= threshold:
                matches.append(SkillMatch(skill, score, reasons))
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]


@dataclass
class SkillState:
    """Per-conversation skill context shared by the router, the prompt middleware and the tools."""

    question: str = ""
    active: list[SkillMatch] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)  # added by load_skill; persist for the conversation

    def set_question(self, question: str, matches: list[SkillMatch]) -> None:
        self.question = question
        self.active = matches

    def names(self) -> list[str]:
        return list(dict.fromkeys([m.skill.name for m in self.active] + self.loaded))


def skills_prompt(registry: SkillRegistry, active: list[SkillMatch], loaded: Iterable[str] = ()) -> str:
    parts = ["# Skills",
             "Specialised playbooks are available. Active skills were selected for this question; follow them. "
             "Call load_skill(name) to load any other skill if the question turns out to need it.",
             "Available skills:\n" + registry.index()]
    chosen = [m.skill for m in active]
    chosen += [registry.skills[n] for n in loaded if n in registry.skills and registry.skills[n] not in chosen]
    if chosen:
        parts.append("Active for this question: " + ", ".join(s.name for s in chosen))
        parts += [s.instructions() for s in chosen]
    return "\n\n".join(parts)


__all__ = ["LIBRARY", "Skill", "SkillMatch", "SkillRegistry", "SkillState", "parse_skill", "skills_prompt"]
