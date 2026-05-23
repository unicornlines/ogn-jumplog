"""Command-line entry point for jumplog."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from jumplog.ogn import (
    AircraftNotFoundError,
    OGNError,
    extract_lifts,
    fetch_flightbook,
)
from jumplog.pdf import SheetMeta, render_sheet


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jumplog",
        description="Generate a pre-filled jump-ops log sheet PDF from OGN FLARM data.",
    )
    p.add_argument("--callsign", required=True, help="Aircraft registration, e.g. N699SA")
    p.add_argument("--date", required=True, help="Day to query, YYYY-MM-DD")
    p.add_argument("--airport", required=True, help="Home airfield ICAO code, e.g. EDEH")
    p.add_argument("--out", required=True, help="Target PDF path")
    p.add_argument("--pilot", default="", help="Pilot name printed in the footer")
    p.add_argument("--operator", default="", help="Operator name printed in the header")
    p.add_argument(
        "--tz",
        choices=["local", "utc"],
        default="local",
        help="Timezone for TO/LDG times (default: local airfield TZ)",
    )
    p.add_argument(
        "--flarm-id",
        default=None,
        help="Hex FLARM device address (skip DDB-based registration lookup)",
    )
    p.add_argument(
        "--allow-empty",
        action="store_true",
        help="Render a blank sheet even when no flights are found for the aircraft",
    )
    return p.parse_args(argv)


def _validate_date(s: str) -> None:
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"jumplog: --date must be YYYY-MM-DD ({exc})")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _validate_date(args.date)

    try:
        payload = fetch_flightbook(args.airport, args.date)
    except OGNError as exc:
        print(f"jumplog: {exc}", file=sys.stderr)
        return 2

    try:
        lifts = extract_lifts(
            payload,
            args.callsign,
            flarm_id=args.flarm_id,
            tz_mode=args.tz,
        )
    except AircraftNotFoundError as exc:
        if args.allow_empty:
            print(f"jumplog: {exc} — rendering empty sheet.", file=sys.stderr)
            lifts = []
        else:
            print(f"jumplog: {exc}", file=sys.stderr)
            return 3

    if not lifts and not args.allow_empty:
        print(
            f"jumplog: no flights found for {args.callsign} at {args.airport} on {args.date}."
            " Pass --allow-empty to render a blank sheet.",
            file=sys.stderr,
        )
        return 4

    meta = SheetMeta(
        callsign=args.callsign,
        airport=args.airport,
        date=args.date,
        pilot=args.pilot,
        operator=args.operator,
        tz_label=args.tz.upper(),
    )
    render_sheet(args.out, meta, lifts)
    print(
        f"jumplog: wrote {args.out} ({len(lifts)} lift(s) for {args.callsign})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
