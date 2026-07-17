"""
verify_ephemeris.py -- Task 1 from the build plan: prove the foundation.

Computes a full set of planet positions and chart angles for a birth whose data
is independently documented, so the output can be checked against astro.com to
the arcminute. Nothing else in the project is worth building until this matches.

Verification chart: ALBERT EINSTEIN
  Astro-Databank / astro.com, Rodden Rating AA (from birth record).
  14 March 1879, 11:30 LMT, Ulm, Germany (48 deg 24' N, 10 deg 00' E).
  Pre-1893 Germany used Local Mean Time. astro.com references Ulm's LMT to
  10 deg E, which is exactly +0:40 ahead of UT. Hence:
        UT = 11:30 (local)  -  0:40  =  10:50 UT.

To verify: open astro.com's chart for Einstein (Placidus, tropical) and compare
each line below. Agreement should be within ~1 arcminute. (The Moon and the
Ascendant are the most time-sensitive lines, so they are the sharpest test.)
"""

from engine import ephemeris as eph

# --- Birth data (all inputs explicit; nothing guessed) -----------------------
NAME = "Albert Einstein"
YEAR, MONTH, DAY = 1879, 3, 14
HOUR, MINUTE = 11, 30              # local clock time (LMT)
UTC_OFFSET_HOURS = 40 / 60          # LMT at 10 deg E = +0:40 ahead of UT
LATITUDE = 48 + 24 / 60             # 48 deg 24' N  -> 48.4000
LONGITUDE = 10 + 0 / 60            # 10 deg 00' E  -> 10.0000


def main() -> None:
    jd_ut = eph.local_to_jd_ut(
        YEAR, MONTH, DAY, HOUR, MINUTE, 0, utc_offset_hours=UTC_OFFSET_HOURS
    )
    ut_hours = HOUR + MINUTE / 60 - UTC_OFFSET_HOURS
    ut_h, ut_m = int(ut_hours), round((ut_hours - int(ut_hours)) * 60)

    print("=" * 64)
    print(f"  EPHEMERIS VERIFICATION  —  {NAME}")
    print("=" * 64)
    print(f"  Birth (local) : {YEAR}-{MONTH:02d}-{DAY:02d}  {HOUR:02d}:{MINUTE:02d}  LMT")
    print(f"  UTC offset    : +{UTC_OFFSET_HOURS*60:.0f} min  (LMT at {LONGITUDE:.2f} E)")
    print(f"  Universal Time: {YEAR}-{MONTH:02d}-{DAY:02d}  {ut_h:02d}:{ut_m:02d}  UT")
    print(f"  Location      : {LATITUDE:.4f} N, {LONGITUDE:.4f} E")
    print(f"  Julian Day UT : {jd_ut:.6f}")
    print(f"  Ephemeris     : {eph.EPHE_BACKEND_NAME}")
    print(f"  Swiss Eph ver : {eph.swiss_ephemeris_version()}")
    print("-" * 64)

    print("  PLANETS")
    for pos in eph.planet_positions(jd_ut):
        print(f"    {pos.name:<8} {pos.formatted():<18}  (lon {pos.longitude:9.5f})")
    print("-" * 64)

    print("  ANGLES")
    angles = eph.chart_angles(jd_ut, LATITUDE, LONGITUDE)
    for label, text in angles.formatted().items():
        lon = {
            "Ascendant": angles.ascendant, "Midheaven": angles.midheaven,
            "Descendant": angles.descendant, "Imum Coeli": angles.imum_coeli,
        }[label]
        print(f"    {label:<11} {text:<18}  (lon {lon:9.5f})")
    print("=" * 64)
    print("  Compare each line to astro.com (Einstein, Placidus, tropical).")
    print("  Expected agreement: within ~1 arcminute.")
    print("=" * 64)


if __name__ == "__main__":
    main()
