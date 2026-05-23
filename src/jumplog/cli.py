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
    summarize_devices,
)
from jumplog.pdf import SheetMeta, lift_to_row, render_sheet


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


def _print_no_match_diagnostics(args: argparse.Namespace, payload: dict, headline: str) -> None:
    devs = payload.get("devices") or []
    flights = payload.get("flights") or []
    af = payload.get("airfield") or {}
    af_name = af.get("name") or "?"

    print(f"jumplog: {headline}", file=sys.stderr)
    print(f"  airfield: {args.airport} ({af_name})", file=sys.stderr)
    print(
        f"  OGN sees {len(devs)} device(s) and {len(flights)} flight(s) at {args.airport}"
        f" on {args.date}.",
        file=sys.stderr,
    )

    if not devs:
        print(
            "  No OGN coverage for this airfield/date — possibly no nearby receiver, "
            "no transponder pickup, or wrong ICAO code.",
            file=sys.stderr,
        )
    else:
        summaries = summarize_devices(payload)
        jump_candidates = [s for s in summaries if s.jump_pattern]
        if jump_candidates:
            print(
                "  Jump-pattern candidates at this airfield (≥4 flights to ≥8000 ft AGL):",
                file=sys.stderr,
            )
            for s in jump_candidates[:5]:
                print(
                    f"    --flarm-id {s.address}   reg={s.registration or '(unknown)'}"
                    f" type={s.aircraft or '?'} flights={s.flight_count}"
                    f" peak={s.peak_alt_ft}ft avg={s.avg_duration_min}min",
                    file=sys.stderr,
                )
        elif summaries:
            print(
                "  All tracked devices at this airfield (no jump-pattern match):",
                file=sys.stderr,
            )
            for s in summaries[:6]:
                print(
                    f"    addr={s.address}  reg={s.registration or '(unknown)'}"
                    f"  type={s.aircraft or '?'}  flights={s.flight_count}"
                    f"  peak={s.peak_alt_ft}ft  avg={s.avg_duration_min}min",
                    file=sys.stderr,
                )

    print(file=sys.stderr)
    print("  Next steps:", file=sys.stderr)
    print(
        "    • If you know the FLARM/Mode-S hex of your aircraft, rerun with "
        "--flarm-id <hex>.",
        file=sys.stderr,
    )
    print(
        "    • If your aircraft is registered in the OGN DDB, double-check the spelling "
        "of --callsign.",
        file=sys.stderr,
    )
    print(
        "    • Or rerun with --allow-empty to print a blank pre-formatted sheet.",
        file=sys.stderr,
    )


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
            _print_no_match_diagnostics(args, payload, str(exc))
            return 3

    if not lifts and not args.allow_empty:
        _print_no_match_diagnostics(
            args, payload,
            f"OGN has 0 flights for {args.callsign} at {args.airport} on {args.date}.",
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
    rows = [lift_to_row(l) for l in lifts]
    render_sheet(args.out, meta, rows)
    print(
        f"jumplog: wrote {args.out} ({len(lifts)} lift(s) for {args.callsign})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
