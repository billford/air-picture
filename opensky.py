"""OpenSky Network REST API fallback for when the local SDR is unavailable."""

import logging
import urllib.error
import urllib.request
import json
import math
from dataclasses import dataclass
from typing import Optional, List

import config

logger = logging.getLogger(__name__)

_OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Bounding box: ~150 nm radius around the observer
_LAT_DELTA = 2.2
_LON_DELTA = 2.8

_M_TO_FT = 3.28084
_MS_TO_KTS = 1.94384


@dataclass
class Aircraft:
    """ADS-B contact returned by the OpenSky Network REST API."""

    icao_hex: str
    callsign: Optional[str]
    altitude_ft: Optional[int]
    speed_kts: Optional[float]
    heading_deg: Optional[float]
    lat: Optional[float]
    lon: Optional[float]


def _distance_nm(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in nautical miles."""
    r = 3440.065  # Earth radius in nm
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_aircraft(radius_nm: float = 150.0) -> List[Aircraft]:
    """Return aircraft within radius_nm of the observer location via OpenSky."""
    lat, lon = config.OBSERVER_LAT, config.OBSERVER_LON
    url = (
        f"{_OPENSKY_URL}"
        f"?lamin={lat - _LAT_DELTA:.4f}"
        f"&lomin={lon - _LON_DELTA:.4f}"
        f"&lamax={lat + _LAT_DELTA:.4f}"
        f"&lomax={lon + _LON_DELTA:.4f}"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "air-picture/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as exc:
        logger.error("OpenSky fetch failed: %s", exc)
        return []

    states = data.get("states") or []
    aircraft = []

    for s in states:
        ac_lat = s[6]
        ac_lon = s[5]
        if ac_lat is None or ac_lon is None:
            continue
        if _distance_nm(lat, lon, ac_lat, ac_lon) > radius_nm:
            continue
        if s[8]:  # on_ground
            continue

        alt_m = s[7]
        speed_ms = s[9]
        aircraft.append(Aircraft(
            icao_hex=(s[0] or "").upper(),
            callsign=(s[1] or "").strip() or None,
            altitude_ft=round(alt_m * _M_TO_FT) if alt_m is not None else None,
            speed_kts=round(speed_ms * _MS_TO_KTS, 1) if speed_ms is not None else None,
            heading_deg=s[10],
            lat=ac_lat,
            lon=ac_lon,
        ))

    logger.info("OpenSky: %d airborne contacts within %.0f nm", len(aircraft), radius_nm)
    return aircraft
