"""
rectify.py -- the honest core, run headless.

Sweeps every candidate birth time, scores each against the real timeline, and
then runs the pure-random NULL MODEL: for each candidate, does the chart fit the
REAL event dates better than it fits RANDOM dates? Ranking is by that
comparison ("percentile among alternatives"), NOT by raw internal_fit -- because
raw fit is biased toward times whose angles happen to be hit-prone.

Honesty guarantees preserved here:
  * Ranking is noise-aware (the null model), not raw.
  * Every stored candidate keeps its internal_fit, evidence_coverage, and
    percentile_among_alternatives; the top candidates keep their full hit ledger.
  * A run records its config, seed, ephemeris + rule versions -> reproducible.
  * The multiple-comparisons caveat is reported, not hidden: with many candidate
    times, some will score high by chance, so a high percentile alone is not proof.

Efficiency: transiting longitudes (date-dependent only) and the solar arc
(age-dependent only) are precomputed on daily grids, so the null model's many
re-evaluations are pure array lookups. Same scoring is used for real and null,
so the comparison is apples-to-apples.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field

import numpy as np

from engine import ephemeris as eph
from engine import scoring
from engine.rules import Rule, ASPECT_ANGLES

TROPICAL_YEAR_DAYS = scoring.TROPICAL_YEAR_DAYS


# =============================================================================
# Precomputed life grids
# =============================================================================
@dataclass
class Grids:
    base_jd: float                       # noon UT of the birth date (day-offset anchor)
    n_days: int
    transit: dict[str, np.ndarray]       # planet -> longitude by day offset
    arc: np.ndarray                      # solar arc (deg) by day offset (age)

    def offset(self, jd: float) -> int:
        return int(min(max(round(jd - self.base_jd), 0), self.n_days - 1))


def build_grids(birth_data, rules: list[Rule], reference_time: str, years: int = 90) -> Grids:
    y, m, d = (int(x) for x in birth_data.birth_date.split("-"))
    base_jd = eph.local_to_jd_ut(y, m, d, 12, 0, 0, utc_offset_hours=0.0)  # noon UT birth date
    n_days = int(years * 365.25)
    offsets = np.arange(n_days)

    # transiting longitudes for every planet used by a transit rule
    transit_points = sorted({r.point for r in rules if r.technique == "transit"})
    transit: dict[str, np.ndarray] = {}
    for name in transit_points:
        transit[name] = np.array([eph.body_longitude(base_jd + int(o), name) for o in offsets])

    # solar arc as a function of age, from the reference birth moment
    ref_jd = scoring._candidate_jd(birth_data, reference_time)
    natal_sun_ref = eph.body_longitude(ref_jd, "Sun")
    arc = np.empty(n_days)
    for o in offsets:
        prog_jd = ref_jd + o / TROPICAL_YEAR_DAYS
        arc[o] = (eph.body_longitude(prog_jd, "Sun") - natal_sun_ref) % 360.0

    return Grids(base_jd=base_jd, n_days=n_days, transit=transit, arc=arc)


# =============================================================================
# Vectorized geometry
# =============================================================================
def _sep_vec(moving: np.ndarray, target: float) -> np.ndarray:
    d = np.abs((moving - target) % 360.0)
    return np.where(d > 180.0, 360.0 - d, d)


def _decay_vec(orb: np.ndarray, max_orb: float) -> np.ndarray:
    sigma = max_orb / 2.0
    val = np.exp(-(orb * orb) / (2.0 * sigma * sigma))
    return np.where(orb <= max_orb, val, 0.0)


# =============================================================================
# Per-candidate real evaluation (grid-based, matches scoring.evaluate_candidate)
# =============================================================================
@dataclass
class CandidateResult:
    local_time: str
    internal_fit: float
    evidence_coverage: float
    percentile_among_alternatives: float = 0.0
    hits: list = field(default_factory=list)   # (event_id, rule_id, technique, point, aspect, target, orb, points)


def _minutes_to_hhmm(minutes: int) -> str:
    hh, mm = divmod(minutes, 60)
    return f"{hh:02d}:{mm:02d}"


def _prep_events(events, rules):
    """Fixed per-event data: (day_offset, salience*reliability, applicable rules, meta)."""
    total_reliability = sum(scoring.reliability(e.date_precision) for e in events)
    prepped = []
    for e in events:
        applicable = [r for r in rules if r.applies(e.category)]
        prepped.append({
            "id": e.id,
            "sr": scoring.salience(e.importance) * scoring.reliability(e.date_precision),
            "reliability": scoring.reliability(e.date_precision),
            "rules": applicable,
            "title": e.title,
            "date": e.event_date,
        })
    return prepped, total_reliability


def _real_eval(natal, target_lon, event_offsets, prepped, total_reliability, grids):
    fit = 0.0
    covered = 0.0
    hits = []
    for meta, off in zip(prepped, event_offsets):
        ev_contrib = 0.0
        ev_hit = False
        for rule in meta["rules"]:
            moving = (grids.transit[rule.point][off] if rule.technique == "transit"
                      else (natal[rule.point] + grids.arc[off]) % 360.0)
            tgt = target_lon[rule.target]
            sep = scoring.angular_separation(moving, tgt)
            best_aspect, best_orb = None, None
            for a in rule.aspects:
                orb = abs(sep - ASPECT_ANGLES[a])
                if orb <= rule.max_orb_deg and (best_orb is None or orb < best_orb):
                    best_aspect, best_orb = a, orb
            if best_aspect is not None:
                decay = scoring.orb_decay(best_orb, rule.max_orb_deg)
                pts = rule.weight * meta["sr"] * decay
                ev_contrib += pts
                ev_hit = True
                hits.append((meta["id"], rule.id, rule.technique, rule.point,
                             best_aspect, rule.target, best_orb, pts))
        fit += ev_contrib
        if ev_hit:
            covered += meta["reliability"]
    coverage = covered / total_reliability if total_reliability else 0.0
    return fit, coverage, hits


def _null_fits(natal, target_lon, prepped, grids, K, rng, day_lo, day_hi):
    """K null internal_fits: keep each event's category/importance/precision,
    redraw its DATE uniformly at random over the life window (Stage-1 pure random)."""
    n = len(prepped)
    offs = rng.integers(day_lo, day_hi, size=(K, n))
    total = np.zeros(K)
    for i, meta in enumerate(prepped):
        col = offs[:, i]
        ev = np.zeros(K)
        for rule in meta["rules"]:
            moving = (grids.transit[rule.point][col] if rule.technique == "transit"
                      else (natal[rule.point] + grids.arc[col]) % 360.0)
            sep = _sep_vec(moving, target_lon[rule.target])
            orbs = np.stack([np.abs(sep - ASPECT_ANGLES[a]) for a in rule.aspects])
            best = orbs.min(axis=0)
            ev += rule.weight * meta["sr"] * _decay_vec(best, rule.max_orb_deg)
        total += ev
    return total


# =============================================================================
# The sweep
# =============================================================================
@dataclass
class SweepResult:
    candidates: list                 # CandidateResult, ranked (best first)
    step_minutes: int
    null_iterations: int
    seed: int
    config: dict


def run_sweep(birth_data, events, rules, step_minutes=2, null_iterations=300,
              seed=20260717, reference_time="12:00", life_years=90) -> SweepResult:
    rng = np.random.default_rng(seed)
    grids = build_grids(birth_data, rules, reference_time, years=life_years)
    prepped, total_reliability = _prep_events(events, rules)

    # null draws over an adult life window (Stage-1 pure random)
    day_lo, day_hi = int(1 * 365.25), int(min(life_years, 88) * 365.25)

    # sweep window
    sh, sm = (int(x) for x in birth_data.search_start.split(":"))
    eh, em = (int(x) for x in birth_data.search_end.split(":"))
    start_min, end_min = sh * 60 + sm, eh * 60 + em

    results: list[CandidateResult] = []
    for minute in range(start_min, end_min + 1, step_minutes):
        hhmm = _minutes_to_hhmm(minute)
        natal_jd = scoring._candidate_jd(birth_data, hhmm)
        natal = {p.name: p.longitude for p in eph.planet_positions(natal_jd)}
        angles = eph.chart_angles(natal_jd, birth_data.latitude, birth_data.longitude)
        target_lon = {"ASC": angles.ascendant, "MC": angles.midheaven}

        event_offsets = [grids.offset(scoring._event_noon_jd(m["date"])) for m in prepped]
        fit, coverage, hits = _real_eval(natal, target_lon, event_offsets,
                                         prepped, total_reliability, grids)

        nulls = _null_fits(natal, target_lon, prepped, grids, null_iterations, rng, day_lo, day_hi)
        # percentile among alternatives: fraction of random timelines this chart beats
        pct = float(np.mean(fit > nulls))

        results.append(CandidateResult(
            local_time=hhmm, internal_fit=fit, evidence_coverage=coverage,
            percentile_among_alternatives=pct, hits=hits,
        ))

    # HONEST RANKING: by null-model standing first, then coverage, then raw fit.
    results.sort(key=lambda c: (c.percentile_among_alternatives, c.evidence_coverage, c.internal_fit),
                 reverse=True)

    config = {
        "techniques": sorted({r.technique for r in rules}),
        "n_rules": len(rules), "n_events": len(events),
        "step_minutes": step_minutes, "null_iterations": null_iterations,
        "normalization": "stage1_pure_random", "life_years": life_years,
        "reference_time_for_grids": reference_time,
    }
    return SweepResult(candidates=results, step_minutes=step_minutes,
                       null_iterations=null_iterations, seed=seed, config=config)


# =============================================================================
# Persistence
# =============================================================================
def _hhmm_to_min(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def summarize(sweep: "SweepResult") -> dict:
    """The shared honest readout: result state (by separation, not raw score),
    the multiple-comparisons context, and the top region. Used by both the CLI
    and the UI so they never disagree."""
    cands = sweep.candidates
    pcts = np.array([c.percentile_among_alternatives for c in cands])
    top = cands[0]
    top_min = _hhmm_to_min(top.local_time)
    # second DISTINCT region (skip near-duplicate adjacent minutes)
    second_pct = next(
        (c.percentile_among_alternatives for c in cands[1:]
         if abs(_hhmm_to_min(c.local_time) - top_min) > 20),
        cands[1].percentile_among_alternatives if len(cands) > 1 else 0.0,
    )
    gap = top.percentile_among_alternatives - second_pct
    if gap < 0.03:
        state = "UNRESOLVED — no candidate separates from the field"
    elif gap < 0.10:
        state = "WEAKLY LEANING — a front-runner, but not clear"
    else:
        state = "SEPARATED — one region stands clear"
    return {
        "state": state,
        "top_time": top.local_time,
        "top_pct": top.percentile_among_alternatives,
        "second_pct": second_pct,
        "gap": gap,
        "n_ceiling": int(np.sum(pcts >= 0.999)),
        "n": len(cands),
    }


def save_run(conn, subject_id, sweep: SweepResult, rules_path: str, top_k_hits=20) -> int:
    from engine import store
    ruleset_hash = store.ruleset_fingerprint(rules_path)
    cur = conn.execute(
        """INSERT INTO runs
           (subject_id, created_utc, config_json, rng_seed, swisseph_version,
            ephemeris_backend, tz_handling, ruleset_id, ruleset_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, store._utcnow(), json.dumps(sweep.config), sweep.seed,
         eph.swiss_ephemeris_version(), eph.EPHE_BACKEND_NAME, "explicit_utc_offset",
         "v1-angles-core", ruleset_hash),
    )
    run_id = int(cur.lastrowid)

    for rank, c in enumerate(sweep.candidates):
        cur = conn.execute(
            """INSERT INTO candidates
               (run_id, local_time, internal_fit, percentile_among_alternatives, evidence_coverage)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, c.local_time, c.internal_fit, c.percentile_among_alternatives, c.evidence_coverage),
        )
        cid = int(cur.lastrowid)
        if rank < top_k_hits:
            for (eid, rid, tech, point, aspect, target, orb, pts) in c.hits:
                conn.execute(
                    """INSERT INTO hits
                       (run_id, candidate_id, event_id, rule_id, technique, point, aspect, target, orb, points)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, cid, eid, rid, tech, point, aspect, target, orb, pts),
                )
    conn.commit()
    return run_id
