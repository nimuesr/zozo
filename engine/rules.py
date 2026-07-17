"""
rules.py -- load the frozen rule set from rules.yaml into structured objects.

The rules are DATA, committed and frozen (see rules.yaml). This module only
reads and validates them; it never invents or edits a rule. Nothing here scores
anything -- it just makes the frozen rules usable by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import yaml

# The only aspects V1 uses. Conjunction + opposition to ASC and MC together cover
# all four angles (opp ASC = Descendant, opp MC = IC) with no double-counting.
ASPECT_ANGLES: dict[str, float] = {"conjunction": 0.0, "opposition": 180.0}

VALID_TECHNIQUES = {"transit", "solar_arc"}
VALID_TARGETS = {"ASC", "MC"}


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    technique: str           # 'transit' | 'solar_arc'
    point: str               # planet name, e.g. 'Saturn'
    aspects: tuple[str, ...] # e.g. ('conjunction', 'opposition')
    target: str              # 'ASC' | 'MC'
    max_orb_deg: float
    weight: float
    applies_to: tuple[str, ...]  # e.g. ('career', 'education', 'public') or ('any',)

    def applies(self, category: str) -> bool:
        return "any" in self.applies_to or category in self.applies_to


def load_rules(path: str) -> list[Rule]:
    with open(path) as fh:
        doc = yaml.safe_load(fh)

    rules: list[Rule] = []
    for r in doc["rules"]:
        rid = r["id"]
        if r["technique"] not in VALID_TECHNIQUES:
            raise ValueError(f"{rid}: technique must be one of {VALID_TECHNIQUES}")
        if r["target"] not in VALID_TARGETS:
            raise ValueError(f"{rid}: target must be one of {VALID_TARGETS}")
        for a in r["aspects"]:
            if a not in ASPECT_ANGLES:
                raise ValueError(f"{rid}: unknown aspect {a!r}")

        applies = r["applies_to"]
        applies_tuple = ("any",) if applies == "any" else tuple(applies)

        rules.append(
            Rule(
                id=rid,
                name=r["name"],
                technique=r["technique"],
                point=r["point"],
                aspects=tuple(r["aspects"]),
                target=r["target"],
                max_orb_deg=float(r["max_orb_deg"]),
                weight=float(r["weight"]),
                applies_to=applies_tuple,
            )
        )

    if not rules:
        raise ValueError("no rules found in rules.yaml")
    return rules
