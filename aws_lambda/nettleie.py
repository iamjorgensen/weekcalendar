"""
Elvia's grid fee (nettleie) for households, from Elvia's tariff sheets ("Tariffblad 1.0, standard
nettleietariff for forbrukerkunder"). All prices include VAT, elavgift and the Enova fee.

- Energiledd: per kWh, "dag" on weekdays 06-22, "natt/helg" at night, at weekends and on public holidays.
- Fastledd (capacity): a monthly amount set by the average of the month's three highest daily peaks
  (døgnmaks = the clock hour with the highest kWh that day).

Add a row to TARIFFS when Elvia publishes new prices (usually 1 January and sometimes 1 July).
"""
from datetime import date, timedelta

# (valid from, dag kr/kWh, natt/helg kr/kWh, [(upper limit kW or None, kr per month), ...])
TARIFFS = [
    (date(2026, 1, 1), 0.3640, 0.2640,
     [(2, 125), (5, 190), (10, 300), (15, 410), (20, 520), (25, 630), (50, 1175), (75, 1720), (100, 2270),
      (None, 4570)]),
    (date(2026, 7, 1), 0.4640, 0.3140,
     [(2, 150), (5, 250), (10, 420), (15, 585), (20, 755), (25, 925), (50, 1760), (75, 2600), (100, 3440),
      (None, 6800)]),
]


def tariff(d):
    """The tariff in force on date d (the oldest one for dates before the table starts)."""
    current = TARIFFS[0]
    for t in TARIFFS:
        if t[0] <= d:
            current = t
    return current


def capacity_fee(peak_kw, d):
    """kr per month for an average top-3 peak of `peak_kw`, at the tariff in force on d."""
    for limit, kr in tariff(d)[3]:
        if limit is None or peak_kw <= limit:
            return kr
    return tariff(d)[3][-1][1]


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * m_) // 451
    return date(year, (h + m_ - 7 * m + 114) // 31, (h + m_ - 7 * m + 114) % 31 + 1)


_holidays = {}


def holidays(year):
    """Norwegian public holidays (red days), which use the night/weekend rate."""
    if year not in _holidays:
        e = _easter(year)
        _holidays[year] = {date(year, 1, 1), e - timedelta(days=3), e - timedelta(days=2), e,
                           e + timedelta(days=1), date(year, 5, 1), date(year, 5, 17), e + timedelta(days=39),
                           e + timedelta(days=49), e + timedelta(days=50), date(year, 12, 25), date(year, 12, 26)}
    return _holidays[year]


def is_workday(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def is_day_hour(d, hour):
    """True when an hour starting at `hour` on date d is billed at the day rate."""
    return is_workday(d) and 6 <= hour < 22


def energy_cost(d, day_kwh, night_kwh):
    t = tariff(d)
    return day_kwh * t[1] + night_kwh * t[2]
