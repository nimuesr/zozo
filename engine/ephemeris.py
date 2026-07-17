"""
ephemeris.py -- the accuracy core of the rectification engine.

Everything astronomical happens here, via the Swiss Ephemeris (pyswisseph).
The rest of the app treats this module as the single source of truth for
"where were the planets and the chart angles at a given moment and place."

Design commitments (from the frozen blueprint):
  * Internally, all times are Universal Time (UT). Civil/local clock time is
    converted to UT at the boundary (see local_to_jd_ut). Timezone/DST is a
    notorious bug source, so the conversion is explicit and never guessed.
  * Positions are tropical, geocentric, apparent -- matching astro.com defaults.
  * Backend is the Moshier ephemeris (FLG_MOSEPH): no external data files, and
    accurate to well under one arcminute for modern dates, so it agrees with
    astro.com's Swiss Ephemeris within the Task-1 verification tolerance. To pin
    the gold-standard JPL-derived files instead, download the .se1 files, call
    swe.set_ephe_path(<dir>), and switch EPHE_FLAG to FLG_SWIEPH (one line).

Nothing in this module interprets a chart or scores anything. It only computes.
"""

from __future__ import annotations

from dataclasses import dataclass
import swisseph as swe

# --- Configuration (these belong in every run's reproducibility log) ---------
# Moshier: file-free, deterministic, sub-arcminute agreement with astro.com.
EPHE_FLAG = swe.FLG_MOSEPH | swe.FLG_SPEED
EPHE_BACKEND_NAME = "Moshier (built-in, file-free)"

# House system for angle computation. The Ascendant and MC are IDENTICAL across
# house systems, so this choice does not affect V1 (which scores only angles).
# 'P' = Placidus (astro.com's default), kept so future house work also matches.
HOUSE_SYSTEM = b"P"

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# All ten bodies are computed for context. The frozen V1 rules actually use:
#   solar arc: Sun, Venus, Saturn      transits: Saturn, Jupiter, Uranus, Pluto
PLANETS: dict[str, int] = {
    "Sun": swe.SUN,        "Moon": swe.MOON,       "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,    "Mars": swe.MARS,       "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,  "Uranus": swe.URANUS,   "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
}


def _dms(degrees: float) -> tuple[int, int, int]:
    """Split a positive degree value into (deg, arcmin, arcsec)."""
    d = int(degrees)
    m_full = (degrees - d) * 60
    m = int(m_full)
    s = round((m_full - m) * 60)
    if s == 60:  # rounding carry
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return d, m, s


def sign_name(longitude: float) -> str:
    """Zodiac sign containing the given ecliptic longitude."""
    return ZODIAC_SIGNS[int((longitude % 360) // 30)]


def format_zodiacal(longitude: float, retrograde: bool = False) -> str:
    """Render an ecliptic longitude as e.g. "23 Pi 30'42\"" (+ ' R' if retro)."""
    lon = longitude % 360.0
    sign_index = int(lon // 30)
    deg_in_sign = lon - sign_index * 30
    d, m, s = _dms(deg_in_sign)
    sign = ZODIAC_SIGNS[sign_index]
    tag = " R" if retrograde else ""
    return f"{d:2d}\u00b0{m:02d}'{s:02d}\" {sign}{tag}"


@dataclass(frozen=True)
class Position:
    name: str
    longitude: float          # ecliptic longitude, 0-360
    latitude: float
    speed_long: float         # deg/day; negative => retrograde

    @property
    def retrograde(self) -> bool:
        return self.speed_long < 0

    @property
    def sign(self) -> str:
        return ZODIAC_SIGNS[int((self.longitude % 360) // 30)]

    @property
    def degree_in_sign(self) -> float:
        return (self.longitude % 360) - int((self.longitude % 360) // 30) * 30

    def formatted(self) -> str:
        return format_zodiacal(self.longitude, self.retrograde)


@dataclass(frozen=True)
class Angles:
    ascendant: float          # ecliptic longitude of the Ascendant
    midheaven: float          # ecliptic longitude of the Midheaven (MC)

    @property
    def descendant(self) -> float:
        return (self.ascendant + 180.0) % 360.0

    @property
    def imum_coeli(self) -> float:
        return (self.midheaven + 180.0) % 360.0

    def formatted(self) -> dict[str, str]:
        return {
            "Ascendant": format_zodiacal(self.ascendant),
            "Midheaven": format_zodiacal(self.midheaven),
            "Descendant": format_zodiacal(self.descendant),
            "Imum Coeli": format_zodiacal(self.imum_coeli),
        }


def swiss_ephemeris_version() -> str:
    """The underlying Swiss Ephemeris library version (pin this per run)."""
    return swe.version


def local_to_jd_ut(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int = 0,
    utc_offset_hours: float = 0.0,
) -> float:
    """Convert a CIVIL (local) datetime plus its UTC offset to Julian Day (UT).

    Convention: local = UT + offset, therefore UT = local - offset.
      * A standard zone east of Greenwich (e.g. CET, +1) -> utc_offset_hours=+1.
      * Local Mean Time at 10 deg E (Einstein/Ulm) -> +40 min -> +40/60 hours.
    Fractional/out-of-range hours are fine: Julian Day is continuous, so day
    rollovers are handled automatically by the linear hour term.
    """
    ut_decimal_hours = hour + minute / 60.0 + second / 3600.0 - utc_offset_hours
    return swe.julday(year, month, day, ut_decimal_hours, swe.GREG_CAL)


def planet_positions(jd_ut: float) -> list[Position]:
    """Tropical geocentric positions of the ten bodies at the given JD (UT)."""
    out: list[Position] = []
    for name, ipl in PLANETS.items():
        values, retflag = swe.calc_ut(jd_ut, ipl, EPHE_FLAG)
        if retflag < 0:
            raise RuntimeError(f"Swiss Ephemeris failed for {name}: retflag={retflag}")
        lon, lat, _dist, speed_long, _lat_speed, _dist_speed = values
        out.append(Position(name=name, longitude=lon, latitude=lat, speed_long=speed_long))
    return out


def body_longitude(jd_ut: float, name: str) -> float:
    """Ecliptic longitude of a single body at the given JD (UT).

    A lean helper for cases that need only one position -- e.g. the
    secondary-progressed Sun that solar arc depends on -- without computing all
    ten bodies.
    """
    values, retflag = swe.calc_ut(jd_ut, PLANETS[name], EPHE_FLAG)
    if retflag < 0:
        raise RuntimeError(f"Swiss Ephemeris failed for {name}: retflag={retflag}")
    return values[0]


def chart_angles(jd_ut: float, latitude: float, longitude: float) -> Angles:
    """Ascendant and Midheaven at the given JD (UT) and geographic location.

    latitude/longitude in decimal degrees (N and E positive). These angles are
    the only birth-time-sensitive quantities V1 scores against.
    """
    _cusps, ascmc = swe.houses(jd_ut, latitude, longitude, HOUSE_SYSTEM)
    return Angles(ascendant=ascmc[0], midheaven=ascmc[1])
