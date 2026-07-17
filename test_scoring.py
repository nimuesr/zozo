"""
test_scoring.py -- Task 3: prove the core scoring function.

Three parts:
  A. Hand-checked unit assertions for every geometry/weighting helper.
  B. evaluate_candidate() on Einstein's REAL chart -> the scored hit ledger,
     plus an independent recomputation of one hit's points (end-to-end check).
  C. Sanity: internal_fit changes with the candidate time (it must, or the whole
     idea is broken) -- a preview of why the sweep exists.
"""

import os
import math
from engine import store, scoring
from engine.rules import load_rules, ASPECT_ANGLES

DB = os.path.join(os.path.dirname(__file__), "data", "rectify.db")
RULES = os.path.join(os.path.dirname(__file__), "rules.yaml")


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def part_a_unit_checks():
    print("A. HAND-CHECKED UNIT ASSERTIONS")

    # angular_separation
    assert approx(scoring.angular_separation(10, 40), 30)
    assert approx(scoring.angular_separation(350, 20), 30)     # wrap
    assert approx(scoring.angular_separation(10, 200), 170)    # >180 raw -> minimal
    # aspect_orb: conjunction and opposition
    assert approx(scoring.aspect_orb(100.0, 100.5, 0.0), 0.5)
    assert approx(scoring.aspect_orb(100.0, 280.3, 180.0), 0.3)   # 179.7 from 180
    # orb_decay: 1.0 at 0, exp(-0.5) at half-orb, exp(-2) at max, 0 beyond
    assert approx(scoring.orb_decay(0.0, 1.5), 1.0)
    assert approx(scoring.orb_decay(0.75, 1.5), math.exp(-0.5))
    assert approx(scoring.orb_decay(1.5, 1.5), math.exp(-2.0))
    assert approx(scoring.orb_decay(1.6, 1.5), 0.0)
    # salience: (imp/10)^1.5
    assert approx(scoring.salience(10), 1.0)
    assert approx(scoring.salience(8), 0.8 ** 1.5)
    assert approx(scoring.salience(5), 0.5 ** 1.5)
    # reliability lookup
    assert approx(scoring.reliability("exact_day"), 1.0)
    assert approx(scoring.reliability("year_only"), 0.5)
    print("   all helper assertions passed.\n")


def part_b_einstein(rules, birth, events):
    print("B. evaluate_candidate() ON EINSTEIN'S KNOWN CHART (11:30)")
    ev = scoring.evaluate_candidate(birth, birth.known_time, events, rules)

    by_id = {e.id: e for e in events}
    print(f"   internal_fit = {ev.internal_fit:.4f}   ({len(ev.hits)} hits)")
    if ev.hits:
        print(f"   {'rule':<16}{'technique':<11}{'aspect':<12}{'tgt':<5}{'orb':>6}  {'pts':>6}  event")
        for h in sorted(ev.hits, key=lambda h: -h.points):
            e = by_id[h.event_id]
            print(f"   {h.rule_id:<16}{h.technique:<11}{h.aspect:<12}{h.target:<5}"
                  f"{h.orb:6.2f}  {h.points:6.3f}  {e.event_date} {e.title[:34]}")

        # END-TO-END CHECK: recompute the top hit's points independently.
        top = max(ev.hits, key=lambda h: h.points)
        e = by_id[top.event_id]
        rule = next(r for r in rules if r.id == top.rule_id)
        expected = (
            rule.weight
            * scoring.salience(e.importance)
            * scoring.reliability(e.date_precision)
            * scoring.orb_decay(top.orb, rule.max_orb_deg)
        )
        assert approx(top.points, expected, tol=1e-9), (top.points, expected)
        print(f"\n   end-to-end recompute of top hit ({top.rule_id}): "
              f"{top.points:.6f} == {expected:.6f}  OK")
    else:
        print("   (no rules fired within orb at this time)")

    # every hit must respect its rule's max orb, and category scoping
    for h in ev.hits:
        rule = next(r for r in rules if r.id == h.rule_id)
        assert h.orb <= rule.max_orb_deg + 1e-9
        assert rule.applies(by_id[h.event_id].category)
    print("   all hits within max_orb and correctly category-scoped.\n")
    return ev


def part_c_sensitivity(rules, birth, events):
    print("C. THE HONEST LANDSCAPE (coarse 10-min scan of the whole day)")
    scan = []
    for minutes in range(0, 24 * 60, 10):
        hh, mm = divmod(minutes, 60)
        t = f"{hh:02d}:{mm:02d}"
        ev = scoring.evaluate_candidate(birth, t, events, rules)
        scan.append((t, ev.internal_fit, len(ev.hits)))

    nonzero = [s for s in scan if s[1] > 0]
    ranked = sorted(scan, key=lambda s: -s[1])
    known_fit = dict((t, f) for t, f, _ in scan)[birth.known_time]
    known_rank = next(i for i, (t, _, _) in enumerate(ranked) if t == birth.known_time)
    pct = 100 * (1 - known_rank / len(scan))

    print(f"   {len(nonzero)}/{len(scan)} times light up at all; the fit surface has many peaks.")
    print(f"   KNOWN time {birth.known_time}: fit {known_fit:.2f}, "
          f"rank {known_rank + 1}/{len(scan)} (~{pct:.0f}th percentile).")
    print("   top 5 times by RAW fit:")
    for t, f, n in ranked[:5]:
        mark = "  <- KNOWN TIME" if t == birth.known_time else ""
        print(f"      {t}   fit {f:5.2f}   hits {n}{mark}")
    print("   --> Raw fit does NOT isolate the true time: several WRONG times score")
    print("       higher, purely because some chart happens to light up there. This is")
    print("       exactly why the pure-random NULL MODEL and honest 'unresolved' language")
    print("       are load-bearing, not decoration. (Dean's critique, made concrete.)")
    print()


def main():
    rules = load_rules(RULES)
    conn = store.connect(DB)
    birth = store.get_birth_data(conn, 1)
    events = store.list_events(conn, 1)
    conn.close()

    print("=" * 78)
    print(f"  TASK 3 — CORE SCORING FUNCTION   ({len(rules)} frozen rules, "
          f"{len(events)} events)")
    print("=" * 78)
    part_a_unit_checks()
    part_b_einstein(rules, birth, events)
    part_c_sensitivity(rules, birth, events)
    print("=" * 78)
    print("  Core scoring function works: rules -> scored, traceable hits -> internal_fit.")
    print("=" * 78)


if __name__ == "__main__":
    main()
