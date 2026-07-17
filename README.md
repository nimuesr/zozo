# Chart Rectification — a research instrument

A personal, calculation-first tool that ranks candidate birth times by how well
they fit a documented life-event timeline — and is honest about how little that
proves. Rankings, never certainty. Every score is traceable to a specific
astronomical contact. The scoring rules are frozen, pre-registered, and clearly
labelled as **untested hypotheses**.

> This tool cannot determine a true birth time. It ranks candidates by internal
> fit to logged events versus random timelines. Every number is relative and
> within-system — not a probability of being correct. Validate only on charts
> with independently-known times, entered blind; your own chart is exploration.

## What it does

For a person's birth date + place and a timeline of dated life events, it:

1. sweeps every candidate birth time across the day,
2. scores each using seven frozen rules — contacts from **transits** and
   **solar-arc directions** to the chart's **angles** (Ascendant / Midheaven),
   weighted by event importance and date reliability,
3. runs a **pure-random null model** (does the chart fit the *real* timeline
   better than *random* ones?) and ranks by that, not by raw fit,
4. reports the result honestly — including "**unresolved**" when no birth time
   separates from the field, and the multiple-comparisons caveat.

It performs **no AI** scoring and makes **no** certainty claims.

## Requirements

Python 3.10+. Install dependencies:

```bash
pip install -r requirements.txt
```

(`pyswisseph`, `pyyaml`, `numpy`; the UI additionally uses `streamlit`.)

## Quick start

```bash
# 1. prove the ephemeris matches a known chart (Task 1)
python verify_ephemeris.py

# 2. create the database + seed a documented validation chart (Einstein)
python seed_example.py

# 3. (optional) run the scoring unit tests + a hand-checked example
python test_scoring.py

# 4. run a full rectification headless (sweep + null model + honest ranking)
python run_rectification.py

# 5. launch the UI
streamlit run app.py
```

## Project layout

```
rectify/
  engine/
    ephemeris.py   astronomical core (planets, angles) via Swiss Ephemeris
    store.py       SQLite data layer (subjects, birth data, events, runs, ...)
    rules.py       loads the frozen rules
    scoring.py     per-hit scoring + the atomic evaluate_candidate()
    rectify.py     sweep + pure-random null model + ranking + persistence
  rules.yaml       the seven FROZEN scoring rules (do not tune to fit a chart)
  verify_ephemeris.py   Task 1 — prove the foundation
  seed_example.py       Task 2 — seed the data spine
  test_scoring.py       Task 3 — prove the scoring loop
  run_rectification.py  Task 4 — the honest core, headless
  app.py                Task 5 — the Streamlit UI
```

## The frozen rules

Seven rules in `rules.yaml`, chosen from tradition **before** any fitting and
frozen. Each carries its traditional provenance, its **empirical status**
(`empirical_support: none_established` for all seven), and a **pre-registered
falsifier** stating what would count against it. Do not edit them to make a chart
fit — validate rule changes on other charts, in a later version.

## Status

The **Minimum Honest Core** is complete: verified ephemeris, data spine with a
reliability model (date precision) and salience (importance), the frozen rule
engine, the candidate sweep, the Stage-1 pure-random null model, honest relative
language, a deterministic (AI-free) results view, and a Streamlit UI.

Deliberately deferred (see the blueprint, Parts I–IV): more techniques,
age-preserving / hybrid null models, blind-testing mode, prediction mode, the
rule-governance lifecycle, and the research journal. The architecture is built so
each slots in without disturbing the core.

## License & dependencies

Choose a license for your own code before publishing (e.g. add a `LICENSE`
file). One dependency needs a careful look first:

- **`pyswisseph`** wraps the **Swiss Ephemeris**, distributed under **AGPL-3.0**
  *or* a separate paid commercial license from Astrodienst. AGPL is strong
  copyleft, so if you publish or host this project, review those terms and pick
  your own license accordingly. Alternatively, the code can run on the built-in
  Moshier backend without the Swiss `.se1` data files (as configured here).
- `numpy`, `pandas`, `streamlit`, `altair`, and `PyYAML` are permissively
  licensed (BSD / MIT-style).

This is a pointer, not legal advice — confirm the current terms yourself.

## An honest note

On the seeded validation chart (Einstein, a known AA-rated time), the tool
currently reports **UNRESOLVED** — two techniques and eight events are not enough
signal to recover a birth time, and it says so rather than fabricating an answer.
That is the tool working as designed. Rigor of process is not evidence that
astrology tracks reality.
