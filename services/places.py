"""offline reverse-geocoding for the Places view — nearest city by haversine over the bundled
GeoNames cities15000 set (CC-BY 4.0). numpy only; no network, no scipy. lazy-loaded + cached."""

import csv
from pathlib import Path

import numpy as np

_DIR = Path(__file__).resolve().parent
_CITIES = _DIR / "places_cities.csv"      # name, cc, lat, lon
_COUNTRIES = _DIR / "places_countries.csv"  # cc, name

_cache = None  # (names, ccs, pops ndarray, lat_rad ndarray, lon_rad ndarray)
_country_names = None
_R_KM = 6371.0
_RADIUS_KM = 30.0  # within this, prefer the most-populous city so a metro reads "Tokyo" not "Eifuku"


def _countries():
    global _country_names
    if _country_names is None:
        m = {}
        try:
            with open(_COUNTRIES, encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2:
                        m[row[0]] = row[1]
        except Exception:
            m = {}
        _country_names = m
    return _country_names


def _load():
    global _cache
    if _cache is not None:
        return _cache
    names, ccs, pops, lats, lons = [], [], [], [], []
    with open(_CITIES, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 4:
                continue
            try:
                lats.append(float(row[2]))
                lons.append(float(row[3]))
                pops.append(int(row[4]) if len(row) > 4 else 0)
            except ValueError:
                continue
            names.append(row[0])
            ccs.append(row[1])
    _cache = (names, ccs, np.array(pops), np.radians(np.array(lats)), np.radians(np.array(lons)))
    return _cache


def nearest(lat, lon):
    """nearest city to (lat, lon) → {'city','country','cc'}, or None if data is unavailable.
    within ~30km, prefer the most-populous city so a district resolves to its parent metro."""
    try:
        names, ccs, pops, clat, clon = _load()
    except Exception:
        return None
    if not names:
        return None
    rlat, rlon = np.radians(float(lat)), np.radians(float(lon))
    dlat = clat - rlat
    dlon = clon - rlon
    a = np.sin(dlat / 2) ** 2 + np.cos(rlat) * np.cos(clat) * np.sin(dlon / 2) ** 2
    d_km = 2 * _R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    near = np.where(d_km <= _RADIUS_KM)[0]
    if len(near):
        i = int(near[np.argmax(pops[near])])  # biggest city nearby
    else:
        i = int(np.argmin(d_km))  # nothing close → strict nearest
    cc = ccs[i]
    return {"city": names[i], "country": _countries().get(cc, cc), "cc": cc}
