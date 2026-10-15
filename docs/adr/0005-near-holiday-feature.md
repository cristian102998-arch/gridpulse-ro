# 0005 – Near-holiday feature (lgbm-v2): kept, gain not significant overall

**Status:** accepted, 2026-10-15

**Context.** Robust anomaly detection on the forecast residuals (median/MAD of the same hour over 28 days) flagged 1.5% of hours. The worst days sat next to public holidays: 2 and 6 January, Easter week, bridge days.

**Decision.** Add `near_holiday` (the day before or after a public holiday). Compare v1 and v2 on the same 365-day walk-forward backtest.

**Result.** MAPE 4.64% → 4.56% over the year; Diebold-Mariano on daily errors: p = 0.15, so not significant overall. On the days next to holidays: 8.64% → 6.43%. v2 is kept because it fixes the failure it targeted without hurting the rest.

**Next.** The biggest remaining misses are sunny spring middays (rooftop solar lowers grid load by up to ~2 GW). Add a solar irradiance forecast.
