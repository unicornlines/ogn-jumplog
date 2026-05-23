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


@dataclass(frozen=True)
class Lift:
    """One take-off/landing pair for the aircraft, derived from OGN."""

    number: int
    takeoff: datetime
    landing: datetime
    max_alt_ft: int
    max_height_ft: int

    @property
    def duration_minutes(self) -> int:
        return round((self.landing - self.takeoff).total_seconds() / 60)

    @property
    def flight_level(self) -> int:
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
        known = ", ".join(sorted({d.get("registration") or d.get("address", "?") for d in devices}))
        hint = f" Aircraft seen at airfield today: {known}." if known else ""
        if flarm_id:
            raise AircraftNotFoundError(
                f"No flights for FLARM id {flarm_id} at this airfield/date.{hint}"
            )
        raise AircraftNotFoundError(
            f"Registration {callsign!r} not found in OGN flightbook devices."
            f" Use --flarm-id <hex> to bypass DDB.{hint}"
        )

    if tz_mode == "utc":
        target_tz: ZoneInfo | timezone = timezone.utc
    elif tz_mode == "local":
        target_tz = _airfield_tz(payload)
    else:
        raise ValueError(f"Unknown tz mode {tz_mode!r}, expected 'local' or 'utc'")

    relevant = [f for f in flights if f.get("device") == dev_idx]
    relevant.sort(key=lambda f: f.get("start_tsp") or 0)

    lifts: list[Lift] = []
    for n, f in enumerate(relevant, start=1):
        start_ts = f.get("start_tsp")
        stop_ts = f.get("stop_tsp")
        if start_ts is None or stop_ts is None:
            continue
        to = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone(target_tz)
        ldg = datetime.fromtimestamp(stop_ts, tz=timezone.utc).astimezone(target_tz)
        lifts.append(
            Lift(
                number=n,
                takeoff=to,
                landing=ldg,
                max_alt_ft=int(f.get("max_alt") or 0),
                max_height_ft=int(f.get("max_height") or 0),
            )
        )
    return lifts


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
