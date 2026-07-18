"""
app.py -- the thin UI for the Chart Rectification research tool (Task 5).

Run locally with:   streamlit run app.py

This is ONLY a face on the engine (ephemeris/store/rules/scoring/rectify). It adds
no astrology and no scoring of its own; it enters data, triggers a run, and
renders the honest, noise-aware results. Every number shown is within-system and
relative -- never a probability of being the true birth time.
"""

import os
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st

from engine import store, scoring, ephemeris as eph, rectify
from engine.rules import load_rules

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "rectify.db")
RULES_PATH = os.path.join(HERE, "rules.yaml")

FRAMING = (
    "This tool ranks candidate birth times by how well they fit your logged events, "
    "**compared with random timelines**. It **cannot determine your true birth time**. "
    "Every number is relative and within-system — not a probability of being correct."
)

CATEGORY_OPTS = ["career", "education", "public", "relationship", "family", "health", "other"]
VALENCE_OPTS = ["positive", "negative", "mixed", "neutral"]
PRECISION_OPTS = ["exact_day", "exact_month", "season", "year_only", "estimated_period"]

st.set_page_config(page_title="Chart Rectification — research", layout="wide")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@st.cache_resource
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return store.init_db(DB_PATH)


@st.cache_resource
def get_rules():
    return load_rules(RULES_PATH)


def rising_sign(birth, hhmm):
    jd = scoring._candidate_jd(birth, hhmm)
    asc = eph.chart_angles(jd, birth.latitude, birth.longitude).ascendant
    return eph.sign_name(asc)


# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #
st.title("Chart Rectification — research instrument")
st.info(FRAMING, icon="⚖️")
st.caption(
    "Calculation-first · rankings never certainty · every score is traceable · "
    "the seven scoring rules are frozen, untested hypotheses (see rules.yaml)."
)

conn = get_conn()
rules = get_rules()


# --------------------------------------------------------------------------- #
# sidebar: subject selection / creation
# --------------------------------------------------------------------------- #
st.sidebar.header("Subject")
subjects = store.list_subjects(conn)
labels = {f"#{s.id} · {s.name}": s.id for s in subjects}
choice = st.sidebar.selectbox("Choose a subject", ["➕ New subject…"] + list(labels.keys()))

if choice == "➕ New subject…":
    with st.sidebar.form("new_subject"):
        new_name = st.text_input("Name")
        new_notes = st.text_area("Notes", height=60)
        if st.form_submit_button("Create subject") and new_name.strip():
            sid = store.add_subject(conn, new_name.strip(), new_notes.strip() or None)
            st.rerun()
    st.stop()

subject_id = labels[choice]
subject = store.get_subject(conn, subject_id)
birth = store.get_birth_data(conn, subject_id)
events = store.list_events(conn, subject_id)

st.sidebar.caption(subject.notes or "")


# --------------------------------------------------------------------------- #
# tabs
# --------------------------------------------------------------------------- #
tab_data, tab_events, tab_run = st.tabs(["1 · Birth data", "2 · Timeline", "3 · Rectify"])

# ---- 1. birth data -------------------------------------------------------- #
with tab_data:
    st.subheader(f"Birth data — {subject.name}")
    with st.form("birth_data"):
        c1, c2, c3 = st.columns(3)
        birth_date = c1.text_input("Birth date (YYYY-MM-DD)", birth.birth_date if birth else "")
        lat = c2.number_input("Latitude (N +)", value=birth.latitude if birth else 0.0, format="%.4f")
        lon = c3.number_input("Longitude (E +)", value=birth.longitude if birth else 0.0, format="%.4f")
        c4, c5, c6 = st.columns(3)
        offset = c4.number_input("UTC offset (hours; local = UT + offset)",
                                 value=birth.utc_offset_hours if birth else 0.0, format="%.4f")
        known = c5.text_input("Known time (HH:MM, optional — VALIDATION ONLY, never rectified)",
                              birth.known_time if birth and birth.known_time else "")
        tz_note = c6.text_input("Timezone note", birth.tz_note if birth and birth.tz_note else "")
        c7, c8 = st.columns(2)
        s_start = c7.text_input("Search window start (HH:MM)", birth.search_start if birth else "00:00")
        s_end = c8.text_input("Search window end (HH:MM)", birth.search_end if birth else "23:59")
        if st.form_submit_button("Save birth data"):
            try:
                store.set_birth_data(conn, subject_id, birth_date.strip(), float(lat), float(lon),
                                     float(offset), tz_note.strip() or None,
                                     known.strip() or None, s_start.strip(), s_end.strip())
                st.session_state.pop("sweep", None)  # birth data changed -> results are stale
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save: {e}")

    if birth and known.strip():
        st.caption(f"Rising sign at the stated known time ({known.strip()}): "
                   f"**{rising_sign(birth, known.strip())}** — shown only for reference; "
                   "the rectification never sees this time.")

# ---- 2. timeline ---------------------------------------------------------- #
with tab_events:
    st.subheader("Life-event timeline")
    st.caption("Reliability comes from **date precision**; salience from **importance**. "
               "Vague, low-importance events contribute little by design.")

    if events:
        df = pd.DataFrame([{
            "date": e.event_date, "title": e.title, "category": e.category,
            "valence": e.valence, "importance": e.importance, "precision": e.date_precision,
        } for e in events])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.write("_No events yet._")

    # --- add --- #
    with st.expander("➕ Add an event"):
        with st.form("add_event"):
            a1, a2 = st.columns(2)
            e_title = a1.text_input("Title")
            e_date = a2.text_input("Date (YYYY-MM-DD)")
            a3, a4, a5 = st.columns(3)
            e_cat = a3.selectbox("Category", CATEGORY_OPTS)
            e_val = a4.selectbox("Valence", VALENCE_OPTS)
            e_imp = a5.slider("Importance", 1, 10, 6)
            e_prec = st.selectbox("Date precision", PRECISION_OPTS)
            if st.form_submit_button("Add event") and e_title.strip() and e_date.strip():
                try:
                    store.add_event(conn, subject_id, e_title.strip(), e_cat, e_val,
                                    e_date.strip(), e_prec, int(e_imp))
                    st.session_state.pop("sweep", None)  # timeline changed -> results are stale
                    st.success("Added.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Could not add: {ex}")

    # --- edit / delete --- #
    if events:
        with st.expander("✏️ Edit or delete an event"):
            emap = {f"{e.event_date} · {e.title}  (#{e.id})": e for e in events}
            pick = st.selectbox("Pick an event", list(emap.keys()), key="edit_pick")
            ev = emap[pick]

            with st.form("edit_event"):
                b1, b2 = st.columns(2)
                u_title = b1.text_input("Title", ev.title, key=f"ut_{ev.id}")
                u_date = b2.text_input("Date (YYYY-MM-DD)", ev.event_date, key=f"ud_{ev.id}")
                b3, b4, b5 = st.columns(3)
                u_cat = b3.selectbox("Category", CATEGORY_OPTS,
                                     index=CATEGORY_OPTS.index(ev.category), key=f"uc_{ev.id}")
                u_val = b4.selectbox("Valence", VALENCE_OPTS,
                                     index=VALENCE_OPTS.index(ev.valence), key=f"uv_{ev.id}")
                u_imp = b5.slider("Importance", 1, 10, int(ev.importance), key=f"ui_{ev.id}")
                u_prec = st.selectbox("Date precision", PRECISION_OPTS,
                                      index=PRECISION_OPTS.index(ev.date_precision), key=f"up_{ev.id}")
                if st.form_submit_button("Save changes") and u_title.strip() and u_date.strip():
                    try:
                        store.update_event(conn, ev.id, u_title.strip(), u_cat, u_val,
                                           u_date.strip(), u_prec, int(u_imp))
                        st.session_state.pop("sweep", None)
                        st.success("Updated.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Could not update: {ex}")

            st.markdown("---")
            confirm = st.checkbox("Yes, permanently delete this event", key=f"del_ok_{ev.id}")
            if st.button("🗑 Delete event", key=f"del_btn_{ev.id}"):
                if confirm:
                    store.delete_event(conn, ev.id)
                    st.session_state.pop("sweep", None)
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.warning("Tick the confirm box first.")

        with st.expander("🧹 Remove several at once (clear a cluster / duplicates)"):
            emap2 = {f"{e.event_date} · {e.title}  (#{e.id})": e for e in events}
            picks = st.multiselect("Select the events to remove", list(emap2.keys()), key="bulk_pick")
            confirm_bulk = st.checkbox(
                f"Yes, permanently delete the {len(picks)} selected event(s)",
                key="bulk_ok", disabled=not picks)
            if st.button("🗑 Delete selected", key="bulk_btn", disabled=not picks):
                if confirm_bulk:
                    n = store.delete_events(conn, [emap2[p].id for p in picks])
                    st.session_state.pop("sweep", None)
                    st.success(f"Deleted {n} event(s).")
                    st.rerun()
                else:
                    st.warning("Tick the confirm box first.")

# ---- 3. rectify ----------------------------------------------------------- #
with tab_run:
    st.subheader("Run a rectification")
    if not birth:
        st.warning("Enter birth data first (tab 1).")
    elif not events:
        st.warning("Add at least a few timeline events first (tab 2).")
    else:
        r1, r2, r3 = st.columns(3)
        step = r1.select_slider("Sweep resolution (minutes)", [1, 2, 3, 4, 5, 10], value=2)
        nulls = r2.select_slider("Null draws (baseline)", [100, 200, 400, 600, 1000], value=400)
        seed = r3.number_input("Random seed", value=20260717, step=1)
        save = st.checkbox("Save this run to the database (reproducible)", value=False)

        if st.button("▶ Run rectification", type="primary"):
            with st.spinner(f"Sweeping the day at {step}-min steps with {nulls} null draws…"):
                sweep = rectify.run_sweep(birth, events, rules, step_minutes=int(step),
                                          null_iterations=int(nulls), seed=int(seed))
                if save:
                    rid = rectify.save_run(conn, subject_id, sweep, RULES_PATH)
                    st.session_state["saved_run"] = rid
            st.session_state["sweep"] = sweep
            st.session_state["sweep_subject"] = subject_id

        # ---- results ---- #
        sweep = st.session_state.get("sweep")
        if sweep and st.session_state.get("sweep_subject") == subject_id:
            cands = sweep.candidates
            summary = rectify.summarize(sweep)

            st.divider()
            st.markdown("### Result")
            colA, colB, colC = st.columns(3)
            colA.metric("Result state", summary["state"].split(" — ")[0])
            colB.metric("Top vs next-region gap", f"{summary['gap']:.3f}")
            colC.metric("Candidates at ceiling", f"{summary['n_ceiling']} / {summary['n']}")
            st.caption(
                f"**{summary['state']}.** With {summary['n']} candidate times, some reach a high "
                "percentile purely by chance (multiple comparisons) — a high number alone is **not** "
                "evidence. What matters is whether one region *separates* from the field."
            )

            # 24-hour fit curve (the centerpiece)
            st.markdown("#### The 24-hour landscape")
            curve = pd.DataFrame([{
                "minutes": rectify._hhmm_to_min(c.local_time),
                "time": c.local_time,
                "internal_fit": c.internal_fit,
                "percentile_among_alternatives": c.percentile_among_alternatives,
                "rising_sign": rising_sign(birth, c.local_time),
            } for c in cands]).sort_values("minutes")

            metric = st.radio("Show", ["internal_fit", "percentile_among_alternatives"],
                              horizontal=True, index=0)
            base = alt.Chart(curve).mark_area(opacity=0.5, interpolate="monotone").encode(
                x=alt.X("minutes:Q", title="birth time",
                        axis=alt.Axis(values=list(range(0, 1441, 120)),
                                      labelExpr="floor(datum.value/60) + 'h'")),
                y=alt.Y(f"{metric}:Q", title=metric.replace("_", " ")),
                tooltip=["time", "rising_sign", alt.Tooltip("internal_fit:Q", format=".2f"),
                         alt.Tooltip("percentile_among_alternatives:Q", format=".3f")],
            )
            layers = [base]
            if birth.known_time:
                kmin = rectify._hhmm_to_min(birth.known_time)
                rule = alt.Chart(pd.DataFrame({"minutes": [kmin]})).mark_rule(
                    color="crimson", strokeDash=[4, 4], size=2).encode(x="minutes:Q")
                layers.append(rule)
            st.altair_chart(alt.layer(*layers).properties(height=260), use_container_width=True)
            if birth.known_time:
                st.caption("Dashed crimson line = the known time (validation only).")

            # rising-sign view (forgiving: a whole sign is a ~2-hour target, not a knife-edge)
            st.markdown("#### Rising sign — the forgiving view")
            st.caption("Even when no single minute wins, one rising sign often still holds more of "
                       "the evidence — a whole sign sits on the horizon for about two hours, a far "
                       "bigger target than one exact minute.")
            sign_df = pd.DataFrame([{
                "rising_sign": rising_sign(birth, c.local_time),
                "internal_fit": c.internal_fit,
            } for c in cands])
            agg = (sign_df.groupby("rising_sign")
                   .agg(total_fit=("internal_fit", "sum"),
                        steps=("internal_fit", "count"),
                        best_fit=("internal_fit", "max"))
                   .reset_index())
            total_all = float(agg["total_fit"].sum())
            steps_all = int(agg["steps"].sum())
            agg["fit_share"] = agg["total_fit"] / total_all if total_all > 0 else 0.0
            agg["window_share"] = agg["steps"] / steps_all
            agg = agg.sort_values("total_fit", ascending=False)

            if total_all <= 0:
                st.info("No rules fired at any time yet — add more events, especially **different "
                        "types** (relationship, family, moves), so the rising-related rules can fire.")
            else:
                top_sign = agg.iloc[0]
                bar = alt.Chart(agg).mark_bar().encode(
                    x=alt.X("total_fit:Q", title="total evidence (summed fit)"),
                    y=alt.Y("rising_sign:N", sort="-x", title=None),
                    tooltip=["rising_sign",
                             alt.Tooltip("total_fit:Q", format=".2f", title="total evidence"),
                             alt.Tooltip("fit_share:Q", format=".0%", title="share of evidence"),
                             alt.Tooltip("window_share:Q", format=".0%", title="share of window (time rising)")],
                ).properties(height=min(360, 26 * len(agg) + 40))
                st.altair_chart(bar, use_container_width=True)
                meaningful = top_sign["fit_share"] > top_sign["window_share"] + 0.03
                st.caption(
                    f"Front-runner: **{top_sign['rising_sign']} rising** — it holds "
                    f"{top_sign['fit_share']:.0%} of the evidence while it's only rising for "
                    f"{top_sign['window_share']:.0%} of the searched window. "
                    + ("It's pulling **more than its share of time** — that's the meaningful case, "
                       "a genuine lean toward this sign."
                       if meaningful else
                       "That's about the **same** as its share of the day, so hold it loosely — it "
                       "may just be rising longer, not fitting better.")
                )
            table = pd.DataFrame([{
                "rank": i + 1,
                "time": c.local_time,
                "rising sign": rising_sign(birth, c.local_time),
                "pct-among-alternatives": round(c.percentile_among_alternatives, 3),
                "evidence coverage": round(c.evidence_coverage, 2),
                "internal fit": round(c.internal_fit, 2),
            } for i, c in enumerate(cands[:15])])
            st.dataframe(table, use_container_width=True, hide_index=True)

            # validation: where did the known time land?
            if birth.known_time:
                krank = next((i for i, c in enumerate(cands) if c.local_time == birth.known_time), None)
                if krank is not None:
                    kc = cands[krank]
                    st.markdown("#### Validation — where the known time landed")
                    v1, v2, v3 = st.columns(3)
                    v1.metric("Known time", birth.known_time)
                    v2.metric("Rank in field", f"{krank + 1} / {len(cands)}")
                    v3.metric("pct-among-alternatives", f"{kc.percentile_among_alternatives:.3f}")
                    st.caption("This is one anecdote (n = 1). It cannot validate the method — only "
                               "many independently-known charts, entered blind, can.")

            # evidence ledger for a chosen candidate
            st.markdown("#### Evidence for a candidate")
            pick = st.selectbox("Inspect candidate",
                                [c.local_time for c in cands[:15]], index=0)
            chosen = next(c for c in cands if c.local_time == pick)
            by_event = {}
            for (eid, rid, tech, point, aspect, target, orb, pts) in chosen.hits:
                by_event.setdefault(eid, []).append((rid, tech, point, aspect, target, orb, pts))
            emap = {e.id: e for e in events}

            supporting = [e for e in events if e.id in by_event]
            contradicting = [e for e in events if e.id not in by_event]

            cL, cR = st.columns(2)
            with cL:
                st.markdown("**Supporting evidence**")
                if supporting:
                    rows = []
                    for e in supporting:
                        for (rid, tech, point, aspect, target, orb, pts) in by_event[e.id]:
                            rows.append({"event": e.title, "rule": rid, "aspect": f"{point} {aspect} {target}",
                                         "orb°": round(orb, 2), "points": round(pts, 2)})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.write("_No rules fired for this candidate._")
            with cR:
                st.markdown("**Contradicting / unexplained events**")
                if contradicting:
                    st.dataframe(pd.DataFrame(
                        [{"event": e.title, "date": e.event_date, "category": e.category}
                         for e in contradicting]), use_container_width=True, hide_index=True)
                    st.caption("Events with no supporting contact at this time. Shown with equal "
                               "prominence on purpose — the evidence *against* matters as much as the evidence for.")
                else:
                    st.write("_Every event has at least one supporting contact._")

            if st.session_state.get("saved_run"):
                st.success(f"Saved as run #{st.session_state['saved_run']} "
                           "(reproducible from config + seed + ruleset hash).")

st.divider()
st.caption(
    "Reminder: a rectified time can never be proven true. Validate on charts with "
    "independently-known times (entered blind), not your own. Rigor of process is not "
    "evidence that astrology tracks reality."
)
