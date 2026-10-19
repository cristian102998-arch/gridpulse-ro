# Power BI report

A Power BI Desktop report on the same marts the app uses. Files: `gridpulse.pbix` (the report), `gridpulse.pdf` (export) and `gridpulse.gif` (a short tour).

## Connect

1. Power BI Desktop → **Get data** → **PostgreSQL database**.
2. Server: the Neon host (e.g. `ep-xxx.eu-central-1.aws.neon.tech`). Database: `gridpulse`. Data connectivity mode: **Import**.
3. Credentials: **Database** → user `gridpulse_app` (read-only) and its password.
4. Select these tables from the `marts` schema:
   `dim_date`, `dim_source`, `fct_generation_hourly`, `fct_load_hourly`, `fct_price_hourly`, `fct_load_forecast_baseline`, `fct_weather_hourly`, `mart_daily_kpis`.

Import keeps the report fast and means Neon is only woken up on refresh. Power BI names the tables `marts dim_date` and so on: rename them to drop the `marts ` prefix, since the measures use the bare names.

## Model (star schema)

Model view → create these relationships (single direction, many-to-one):

| From (many) | To (one) |
|---|---|
| `fct_generation_hourly[local_day]` | `dim_date[date_day]` |
| `fct_generation_hourly[source_code]` | `dim_source[source_code]` |
| `fct_load_hourly[local_day]` | `dim_date[date_day]` |
| `fct_price_hourly[local_day]` | `dim_date[date_day]` |
| `fct_load_forecast_baseline[local_day]` | `dim_date[date_day]` |
| `fct_weather_hourly[local_day]` | `dim_date[date_day]` |
| `mart_daily_kpis[local_day]` | `dim_date[date_day]` |

Then **Table tools → Mark as date table** on `dim_date` (column `date_day`). The year-over-year measures need it.

## Measures

Copy them from [`measures.dax`](measures.dax). Format: `% ` measures as Percentage, GWh with 1 decimal.

Both MAPE measures are computed on the same hours (where the LightGBM backtest exists), so they match the backtest: 4.6% vs 7.2%. `Load YoY %` is blank unless a single year is selected, and last year's load is cut at the last day with data, so a partial year is compared like for like.

## Pages

1. **Overview**: cards (Load GWh, Renewable Share %, Net Position GWh, Load YoY %), a line chart of daily Load GWh by `dim_date[date_day]`, and a slicer on year/month.
2. **Generation mix**: stacked area of Generation GWh by `dim_date[date_day]` with legend `dim_source[source_label]`; a donut of the same by source; a slicer on `dim_source[is_renewable]`.
3. **Forecast**: line chart of `fct_load_forecast_baseline` actual vs LightGBM vs naive for the last 14 days; cards for LightGBM MAPE %, Naive MAPE %, Model Gain pp; a column chart of both MAPEs by month.
4. **Weather vs load**: scatter of daily Load GWh (Y) vs average `fct_weather_hourly[temp_actual_c]` (X), colour by `dim_date[is_weekend]`: the U shape shows heating in winter and cooling in summer.

## Export

File → Export → PDF to `powerbi/gridpulse.pdf`. Record a 20–30 s GIF of clicking through the pages (ScreenToGif is free) to `powerbi/gridpulse.gif`.
