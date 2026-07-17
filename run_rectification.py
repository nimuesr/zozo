"""
run_rectification.py -- Task 4: the honest core, run headless.

Runs the full candidate sweep + pure-random null model on Einstein, ranks by
"percentile among alternatives" (the noise-aware metric), reports where his
KNOWN time actually lands, and saves the reproducible run.

Language: every number is within-system and RELATIVE. This ranks candidate
birth times by how well they fit the logged events versus random timelines. It
CANNOT determine the true birth time.
"""

import os
import numpy as np
from engine import store, scoring, ephemeris as eph
from engine.rules import load_rules
from engine import rectify

DB = os.path.join(os.path.dirname(__file__), "data", "rectify.db")
RULES = os.path.join(os.path.dirname(__file__), "rules.yaml")

STEP_MINUTES = 2
NULL_ITERS = 400
SEED = 20260717


def band(top_pct, second_pct, known_pct, field_pct90):
    """A deliberately conservative, honest label based on separation, not raw score."""
    if top_pct - second_pct < 0.03:
        return "UNRESOLVED (no candidate separates from the field)"
    if top_pct - second_pct < 0.10:
        return "WEAKLY LEANING (a front-runner, but not clear)"
    return "SEPARATED (one region stands clear)"


def main():
    rules = load_rules(RULES)
    conn = store.connect(DB)
    subj = store.get_subject(conn, 1)
    birth = store.get_birth_data(conn, 1)
    events = store.list_events(conn, 1)

    print("=" * 80)
    print(f"  RECTIFICATION RUN — {subj.name}   ({len(rules)} frozen rules, "
          f"{len(events)} events, {STEP_MINUTES}-min sweep, {NULL_ITERS} null draws)")
    print("=" * 80)

    sweep = rectify.run_sweep(birth, events, rules, step_minutes=STEP_MINUTES,
                              null_iterations=NULL_ITERS, seed=SEED)
    cands = sweep.candidates
    n = len(cands)

    # consistency check vs the Task-3 scorer at the known time
    grid_fit = next(c.internal_fit for c in cands if c.local_time == birth.known_time)
    direct = scoring.evaluate_candidate(birth, birth.known_time, events, rules).internal_fit
    print(f"  consistency check @ {birth.known_time}: grid fit {grid_fit:.3f} vs "
          f"direct scorer {direct:.3f}  (nearest-day gridding -> small diff expected)")
    print("-" * 80)

    # ranking is by percentile_among_alternatives (noise-aware), already sorted
    pcts = np.array([c.percentile_among_alternatives for c in cands])
    print("  TOP CANDIDATES  (ranked by percentile-among-alternatives, i.e. how much")
    print("  this chart beats RANDOM timelines — not by raw fit):")
    print(f"    {'time':<7}{'pct-alt':>9}{'coverage':>10}{'fit':>8}   rising sign")
    for c in cands[:8]:
        natal_jd = scoring._candidate_jd(birth, c.local_time)
        asc = eph.chart_angles(natal_jd, birth.latitude, birth.longitude).ascendant
        sign = scoring_sign(asc)
        mark = "  <- KNOWN TIME" if c.local_time == birth.known_time else ""
        print(f"    {c.local_time:<7}{c.percentile_among_alternatives:9.3f}"
              f"{c.evidence_coverage:10.2f}{c.internal_fit:8.2f}   {sign}{mark}")

    # where does the KNOWN time land? (the validation question)
    known_rank = next(i for i, c in enumerate(cands) if c.local_time == birth.known_time)
    known = cands[known_rank]
    print("-" * 80)
    print("  VALIDATION — where does Einstein's KNOWN 11:30 land?")
    print(f"    percentile-among-alternatives = {known.percentile_among_alternatives:.3f}")
    print(f"    rank {known_rank + 1} of {n} candidate times "
          f"(~{100*(1-known_rank/n):.0f}th percentile of the field)")

    # honest separation / multiple-comparisons readout
    top_pct = cands[0].percentile_among_alternatives
    # 2nd DISTINCT time region: skip near-duplicate adjacent minutes
    second_pct = next((c.percentile_among_alternatives for c in cands[1:]
                       if abs(int(c.local_time[:2]) * 60 + int(c.local_time[3:])
                              - (int(cands[0].local_time[:2]) * 60 + int(cands[0].local_time[3:]))) > 20),
                      cands[1].percentile_among_alternatives)
    n_at_ceiling = int(np.sum(pcts >= 0.999))
    print("-" * 80)
    print("  HONEST READOUT")
    print(f"    result state: {band(top_pct, second_pct, known.percentile_among_alternatives, 0)}")
    print(f"    top percentile {top_pct:.3f}; next distinct region {second_pct:.3f}; "
          f"gap {top_pct-second_pct:.3f}")
    print(f"    candidates at the ceiling (>=0.999): {n_at_ceiling} of {n}")
    print(f"    --> With {n} candidate times, some reach a high percentile purely by")
    print(f"        chance (multiple comparisons). A high number alone is NOT evidence;")
    print(f"        what matters is separation, and whether the KNOWN time stands out.")

    run_id = rectify.save_run(conn, subj.id, sweep, RULES)
    stored = conn.execute("SELECT COUNT(*) FROM candidates WHERE run_id=?", (run_id,)).fetchone()[0]
    hits = conn.execute("SELECT COUNT(*) FROM hits WHERE run_id=?", (run_id,)).fetchone()[0]
    conn.close()
    print("-" * 80)
    print(f"  Run #{run_id} saved: {stored} candidates + {hits} hits (top-20). "
          f"Reproducible from config+seed+ruleset hash.")
    print("=" * 80)


def scoring_sign(longitude):
    signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
             "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
    return signs[int((longitude % 360) // 30)]


if __name__ == "__main__":
    main()
