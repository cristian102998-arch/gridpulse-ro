# GridPulse RO

A data platform and AI assistant for the Romanian power system. Work in progress.

**Status (day 1):** the Energy-Charts ingest job loads Romania's 15-minute power mix into Postgres. It is idempotent and handles DST days (23 h / 25 h).

## Quick start

```bash
uv sync
createdb gridpulse            # DATABASE_URL defaults to postgresql://postgres@localhost:5432/gridpulse
uv run gridpulse db init
uv run gridpulse ingest energy-charts public-power --start 2026-10-01 --end 2026-10-14
createdb gridpulse_test && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/gridpulse_test uv run pytest
```

Settings come from environment variables (see `.env.example`). With no dates, `ingest` loads yesterday (local Bucharest day). Re-running the same range changes nothing.

## How the data flows

```
Energy-Charts API ──► raw file (fsspec: data/raw/<source>/<dataset>/YYYY/MM/DD.json)
                  └─► Postgres raw.energy_charts_public_power (one JSON row per local day)
```

## Data sources and attribution

- Power generation and load for Romania: [Energy-Charts](https://www.energy-charts.info/) by Fraunhofer ISE, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## License

MIT
