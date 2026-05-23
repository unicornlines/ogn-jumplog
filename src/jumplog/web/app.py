"""Flask app providing a browser UI for jumplog.

Endpoints:
    GET  /             — single-page form + editable lift table
    POST /api/fetch    — pull OGN flights for callsign/airport/date, return JSON
    POST /api/render   — accept edited rows + meta, return generated PDF

Run locally with `jumplog-web` (defined in pyproject.toml)."""

from __future__ import annotations

import argparse
import io
from dataclasses import asdict

from flask import Flask, jsonify, render_template, request, send_file

from jumplog.ogn import (
    AircraftNotFoundError,
    OGNError,
    extract_lifts,
    fetch_flightbook,
    summarize_devices,
)
from jumplog.pdf import LiftRow, SheetMeta, lift_to_row, render_sheet


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/api/fetch")
    def api_fetch():
        payload = request.get_json(force=True, silent=True) or {}
        callsign = (payload.get("callsign") or "").strip()
        airport = (payload.get("airport") or "").strip()
        date = (payload.get("date") or "").strip()
        flarm_id = (payload.get("flarm_id") or "").strip() or None
        tz_mode = payload.get("tz") or "local"

        missing = [k for k, v in (("callsign", callsign), ("airport", airport), ("date", date)) if not v]
        if missing:
            return jsonify({"error": f"missing required fields: {', '.join(missing)}"}), 400

        try:
            data = fetch_flightbook(airport, date)
        except OGNError as exc:
            return jsonify({"error": str(exc)}), 502

        try:
            lifts = extract_lifts(data, callsign, flarm_id=flarm_id, tz_mode=tz_mode)
        except AircraftNotFoundError as exc:
            candidates = [asdict(s) for s in summarize_devices(data)]
            return jsonify({
                "error": str(exc),
                "airfield": (data.get("airfield") or {}).get("name"),
                "device_count": len(data.get("devices") or []),
                "flight_count": len(data.get("flights") or []),
                "candidates": candidates,
            }), 404

        rows = [asdict(lift_to_row(l)) for l in lifts]
        return jsonify({
            "lifts": rows,
            "airfield": (data.get("airfield") or {}).get("name"),
        })

    @app.post("/api/render")
    def api_render():
        payload = request.get_json(force=True, silent=True) or {}
        meta = SheetMeta(
            callsign=(payload.get("callsign") or "").strip(),
            airport=(payload.get("airport") or "").strip(),
            date=(payload.get("date") or "").strip(),
            pilot=(payload.get("pilot") or "").strip(),
            operator=(payload.get("operator") or "").strip(),
            tz_label=(payload.get("tz") or "").upper(),
        )
        raw_rows = payload.get("lifts") or []
        rows: list[LiftRow] = []
        for i, r in enumerate(raw_rows, start=1):
            rows.append(LiftRow(
                number=i,
                paxe=str(r.get("paxe") or "").strip(),
                fl=str(r.get("fl") or "").strip(),
                to=str(r.get("to") or "").strip(),
                ldg=str(r.get("ldg") or "").strip(),
                time_min=str(r.get("time_min") or "").strip(),
                cyc=str(r.get("cyc") or "").strip(),
                temp=str(r.get("temp") or "").strip(),
                fuel_used=str(r.get("fuel_used") or "").strip(),
                refuel=str(r.get("refuel") or "").strip(),
                remarks=str(r.get("remarks") or "").strip(),
            ))

        buf = io.BytesIO()
        render_sheet(buf, meta, rows)
        buf.seek(0)
        filename = f"logsheet_{meta.airport}_{meta.callsign}_{meta.date}.pdf"
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    return app


def main() -> int:
    p = argparse.ArgumentParser(prog="jumplog-web", description="Run the jumplog web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5050)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    create_app().run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
