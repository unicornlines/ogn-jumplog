# jumplog

Pre-fill a daily jump-operations log sheet PDF from OGN FLARM tracking data.

The tool queries the OGN Flightbook API for the given airfield and date, picks
out the flights of the configured aircraft, and renders an A4-landscape PDF
log sheet with the OGN-derivable columns (lift number, take-off time, landing
time, duration, max altitude) pre-filled. All pilot-side columns (pax count,
engine cycles, fuel, hobbs, engine readings) stay blank to be filled in by
hand during operations.

## Install

```sh
pip install -e .
```

## Use

```sh
jumplog --callsign N699SA --date 2026-05-23 --airport EDEH \
        --pilot "Sophie Bertsch" --operator "Skydive Walldorf" \
        --tz local --out logsheet_2026-05-23.pdf
```

If the registration is not resolvable through the OGN DDB (some U.S. tail
numbers are not registered there), pass the FLARM device address explicitly:

```sh
jumplog --callsign N699SA --flarm-id ABCDEF --date 2026-05-23 \
        --airport EDEH --out logsheet.pdf
```

For a blank sheet without any OGN flights (e.g. day with no data):

```sh
jumplog --callsign N699SA --date 2026-05-23 --airport EDEH \
        --allow-empty --out blank.pdf
```

## Arguments

| Flag | Purpose |
|---|---|
| `--callsign` | Aircraft registration (required) |
| `--date` | Day to fetch, `YYYY-MM-DD` (required) |
| `--airport` | Home airfield ICAO code (required) |
| `--out` | Target PDF path (required) |
| `--pilot` | Pilot name printed in footer (optional) |
| `--operator` | Operator name printed in header (optional) |
| `--tz` | `local` (default) or `utc` for take-off/landing times |
| `--flarm-id` | DDB-bypass: explicit FLARM device address in hex |
| `--allow-empty` | Render a blank sheet if no flights are found |

## Data sources

- OGN Flightbook: `https://flightbook.glidernet.org/api/logbook/<ICAO>/<date>`
- OGN DDB: `https://ddb.glidernet.org/download/?j=1&t=1`

## Dependencies

- reportlab
- requests
- python-dateutil
