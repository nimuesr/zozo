"""
scoring.py -- the heart of the engine: turn a candidate birth time into an
internal-fit score plus a fully traceable list of scored hits.

This is a PURE function of (birth data, candidate time, events, frozen rules).
No sweep, no null model, no UI -- those layer on top later. Every hit records
exactly which rule fired, on which event, with what aspect and orb, and the
points it contributed. Nothing is asserted that isn't backed by a hit.

The per-hit score (the frozen formula, V1 form):

    points = rule_weight  x  salience(importance)  x  reliability(precision)  x  orb_decay(orb)

  * rule_weight        -- the rule's traditional emphasis (from rules.yaml)
  * salience           -- how much the EVENT matters      (from importance 1-10)
  * reliability        -- how much we TRUST the event date (from date_precision)
  * orb_decay          -- tighter aspects score higher     (Gaussian, ->0 at max_orb)

Language note: "internal_fit" is a within-system relative quantity -- how well a
candidate matches the logged events under the frozen rules. It is NOT a
probability of being the true birth time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine import ephemeris as eph
from engine.rules import Rule, ASPECT_ANGLES

# --- Weighting tables (V1). Reliability uses date_precision only; the fuller ---
# --- reliability model is deferred. These are the values from the blueprint. ---
RELIABILITY_BY_PRECISION: dict[str, float] = {
    "exact_day": 1.00,
    "exact_month": 0.85,
    "season": 0.65,
    "year_only": 0.50,
    "estimated_period": 0.30,
}
SALIENCE_GAMMA = 1.5          # importance^1.5 so big events dominate mildly
TROPICAL_YEAR_DAYS = 365.2422  # "a day for a year" scale for solar arc


def reliability(date_precision: str) -> float:
    return RELIABILITY_BY_PRECISION[date_precision]


def salience(importance: int) -> float:
    return (importance / 10.0) ** SALIENCE_GAMMA


def orb_decay(orb: float, max_orb: float) -> float:
    """Gaussian taper: 1.0 at partile, ->0 at max_orb (hard cutoff beyond)."""
    if orb > max_orb:
        return 0.0
    sigma = max_orb / 2.0
    return math.exp(-(orb * orb) / (2.0 * sigma * sigma))


# --- Geometry ---------------------------------------------------------------
def angular_separation(a: float, b: float) -> float:
    """Minimal separation between two ecliptic longitudes, in [0, 180]."""
    d = abs((a - b) % 360.0)
    return 360.0 - d if d > 180.0 else d


def aspect_orb(lon1: float, lon2: float, aspect_angle: float) -> float:
    """Orb (degrees from exact) of a given aspect between two longitudes.
    Works for conjunction (0) and opposition (180)."""
    return abs(angular_separation(lon1, lon2) - aspect_angle)


# --- Time helpers -----------------------------------------------------------
def _candidate_jd(birth_data, hhmm: str) -> float:
    y, m, d = (int(x) for x in birth_data.birth_date.split("-"))
    hh, mm = (int(x) for x in hhmm.split(":"))
    return eph.local_to_jd_ut(y, m, d, hh, mm, 0, utc_offset_hours=birth_data.utc_offset_hours)


def _event_noon_jd(event_date: str) -> float:
    """Transiting positions are read at noon UT of the event date. Slow planets
    (the only ones V1 transits) move <=~2'/day, negligible vs the 1.5 deg orb."""
    y, m, d = (int(x) for x in event_date.split("-"))
    return eph.local_to_jd_ut(y, m, d, 12, 0, 0, utc_offset_hours=0.0)


def solar_arc_degrees(natal_jd: float, natal_sun_lon: float, event_jd: float) -> float:
    """The solar arc at the event: how far the secondary-progressed Sun has
    moved from the natal Sun. 'A day for a year' -> add (age in years) days."""
    years = (event_jd - natal_jd) / TROPICAL_YEAR_DAYS
    progressed_jd = natal_jd + years
    progressed_sun = eph.body_longitude(progressed_jd, "Sun")
    return (progressed_sun - natal_sun_lon) % 360.0


# --- The scored hit ---------------------------------------------------------
@dataclass(frozen=True)
class Hit:
    rule_id: str
    event_id: int
    technique: str
    point: str
    aspect: str
    target: str          # 'ASC' | 'MC'
    orb: float           # degrees from exact
    points: float        # contribution to internal_fit


@dataclass(frozen=True)
class Evaluation:
    candidate_time: str
    internal_fit: float
    hits: tuple[Hit, ...]


def evaluate_candidate(birth_data, candidate_time: str, events, rules: list[Rule]) -> Evaluation:
    """Score one candidate birth time against the timeline under the frozen rules.

    Returns the internal_fit (sum of hit points) and the traceable hit list.
    NOTE: the per-event saturation cap and the pure-random baseline are applied
    in later steps (the sweep + normalization); this is the atomic evaluation.
    """
    natal_jd = _candidate_jd(birth_data, candidate_time)
    natal = {p.name: p.longitude for p in eph.planet_positions(natal_jd)}
    angles = eph.chart_angles(natal_jd, birth_data.latitude, birth_data.longitude)
    target_lon = {"ASC": angles.ascendant, "MC": angles.midheaven}
    natal_sun = natal["Sun"]

    hits: list[Hit] = []
    for ev in events:
        event_jd = _event_noon_jd(ev.event_date)
        transit_lon: dict[str, float] | None = None   # computed lazily, once per event
        arc: float | None = None

        for rule in rules:
            if not rule.applies(ev.category):
                continue

            if rule.technique == "transit":
                if transit_lon is None:
                    transit_lon = {p.name: p.longitude for p in eph.planet_positions(event_jd)}
                moving = transit_lon[rule.point]
            else:  # solar_arc
                if arc is None:
                    arc = solar_arc_degrees(natal_jd, natal_sun, event_jd)
                moving = (natal[rule.point] + arc) % 360.0

            target = target_lon[rule.target]

            # keep the tightest qualifying aspect for this rule/event
            best_aspect: str | None = None
            best_orb: float | None = None
            for aspect_name in rule.aspects:
                orb = aspect_orb(moving, target, ASPECT_ANGLES[aspect_name])
                if orb <= rule.max_orb_deg and (best_orb is None or orb < best_orb):
                    best_aspect, best_orb = aspect_name, orb

            if best_aspect is not None:
                f = orb_decay(best_orb, rule.max_orb_deg)
                points = rule.weight * salience(ev.importance) * reliability(ev.date_precision) * f
                hits.append(Hit(
                    rule_id=rule.id, event_id=ev.id, technique=rule.technique,
                    point=rule.point, aspect=best_aspect, target=rule.target,
                    orb=best_orb, points=points,
                ))

    internal_fit = sum(h.points for h in hits)
    return Evaluation(candidate_time=candidate_time, internal_fit=internal_fit, hits=tuple(hits))
