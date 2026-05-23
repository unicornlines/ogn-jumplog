"""OGN Flightbook client: fetch per-airfield/per-day flight logs and normalize
them into a sequence of Lift records for one aircraft."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

FLIGHTBOOK_URL = "https://flightbook.glidernet.org/api/logbook/{icao}/{date}"


class OGNError(RuntimeError):
    pass


class AircraftNotFoundError(OGNError):
    pass


METERS_TO_FEET = 3.28084


@dataclass(frozen=True)
class Lift:
    """One take-off/landing pair for the aircraft, derived from OGN.

    Altitudes are stored in meters MSL/AGL as OGN delivers them; convert to
    feet at the use-site (e.g. for FL column)."""

    number: int
    takeoff: datetime
    landing: datetime
    max_alt_m: int
    max_height_m: int

    @property
    def duration_minutes(self) -> int:
        return round((self.landing - self.takeoff).total_seconds() / 60)

    @property
    def max_alt_ft(self) -> int:
        return round(self.max_alt_m * METERS_TO_FEET)

    @property
    def max_height_ft(self) -> int:
        return round(self.max_height_m * METERS_TO_FEET)

    @property
    def flight_level(self) -> int:
        """FL = pressure-altitude/100; OGN gives geometric altitude MSL, but
        for jump-log purposes treating max_alt_ft / 100 as the lift altitude is
        the practical convention (drop altitudes are quoted as raw ft/100)."""
        return round(self.max_alt_ft / 100)


def _normalize_registration(reg: str) -> str:
    return reg.strip().upper().replace("-", "").replace(" ", "")


def fetch_flightbook(icao: str, date: str, *, timeout: float = 20.0) -> dict:
    url = FLIGHTBOOK_URL.format(icao=icao.upper(), date=date)
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "jumplog/0.1"})
    except requests.RequestException as exc:
        raise OGNError(f"flightbook request failed: {exc}") from exc
    if resp.status_code != 200:
        raise OGNError(f"flightbook returned HTTP {resp.status_code} for {url}")
    try:
        return resp.json()
    except ValueError as exc:
        raise OGNError(f"flightbook response is not JSON: {exc}") from exc


def _airfield_tz(payload: dict) -> ZoneInfo:
    name = (payload.get("airfield") or {}).get("time_info", {}).get("tz_name")
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _match_device_index(devices: list[dict], callsign: str, flarm_id: str | None) -> int | None:
    if flarm_id:
        wanted = flarm_id.strip().upper()
        for idx, dev in enumerate(devices):
            if (dev.get("address") or "").upper() == wanted:
                return idx
        return None
    wanted = _normalize_registration(callsign)
    for idx, dev in enumerate(devices):
        reg = dev.get("registration")
        if reg and _normalize_registration(reg) == wanted:
            return idx
    return None


def extract_lifts(
    payload: dict,
    callsign: str,
    *,
    flarm_id: str | None = None,
    tz_mode: str = "local",
) -> list[Lift]:
    """Filter flightbook payload by callsign/flarm-id, sort by take-off, and
    return a list of Lift records with timestamps in the requested timezone."""

    devices = payload.get("devices") or []
    flights = payload.get("flights") or []

    if not devices:
        return []

    dev_idx = _match_device_index(devices, callsign, flarm_id)
    if dev_idx is None:
        raise AircraftNotFoundError(
            f"Registration {callsign!r} not found among the {len(devices)} OGN-tracked "
            f"device(s) at this airfield/date." if not flarm_id else
            f"No flights for FLARM id {flarm_id} at this airfield/date "
            f"(saw {len(devices)} device(s))."
        )

    if tz_mode == "utc":
        target_tz: ZoneInfo | timezone = timezone.utc
    elif tz_mode == "local":
        target_tz = _airfield_tz(payload)
    else:
        raise ValueError(f"Unknown tz mode {tz_mode!r}, expected 'local' or 'utc'")

    relevant = [
        f for f in flights
        if f.get("device") == dev_idx
        and f.get("start_tsp") is not None
        and f.get("stop_tsp") is not None
    ]
    relevant.sort(key=lambda f: f.get("start_tsp") or 0)

    lifts: list[Lift] = []
    for n, f in enumerate(relevant, start=1):
        to = datetime.fromtimestamp(f["start_tsp"], tz=timezone.utc).astimezone(target_tz)
        ldg = datetime.fromtimestamp(f["stop_tsp"], tz=timezone.utc).astimezone(target_tz)
        lifts.append(
            Lift(
                number=n,
                takeoff=to,
                landing=ldg,
                max_alt_m=int(f.get("max_alt") or 0),
                max_height_m=int(f.get("max_height") or 0),
            )
        )
    return lifts


@dataclass(frozen=True)
class DeviceSummary:
    address: str
    registration: str | None
    aircraft: str | None
    aircraft_type: int
    flight_count: int
    peak_alt_ft: int
    avg_duration_min: int
    jump_pattern: bool


def summarize_devices(payload: dict) -> list[DeviceSummary]:
    """Per-device summary for diagnostics. Flags `jump_pattern` heuristically
    when a device has >= 4 flights peaking above 8000 ft AGL."""

    devices = payload.get("devices") or []
    flights = payload.get("flights") or []
    by_dev: dict[int, list[dict]] = {}
    for f in flights:
        by_dev.setdefault(f.get("device"), []).append(f)

    out: list[DeviceSummary] = []
    for i, d in enumerate(devices):
        fs = by_dev.get(i, [])
        if not fs:
            continue
        peak_m = max((f.get("max_height") or 0) for f in fs)
        peak_ft = round(peak_m * METERS_TO_FEET)
        durs = [(f.get("duration") or 0) for f in fs]
        avg = round(sum(durs) / len(durs) / 60) if durs else 0
        jump = len(fs) >= 4 and peak_ft >= 8000
        out.append(
            DeviceSummary(
                address=d.get("address") or "?",
                registration=d.get("registration"),
                aircraft=d.get("aircraft"),
                aircraft_type=int(d.get("aircraft_type") or 0),
                flight_count=len(fs),
                peak_alt_ft=peak_ft,
                avg_duration_min=avg,
                jump_pattern=jump,
            )
        )
    out.sort(key=lambda s: (-s.jump_pattern, -s.flight_count))
    return out


def chunks(seq: Iterable[Lift], size: int) -> list[list[Lift]]:
    out: list[list[Lift]] = []
    bucket: list[Lift] = []
    for item in seq:
        bucket.append(item)
        if len(bucket) == size:
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return out
