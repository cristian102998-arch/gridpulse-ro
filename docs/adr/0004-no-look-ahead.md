# 0004 – The forecast only uses what is known on the morning of D-1

**Status:** accepted, 2026-10-15

**Context.** A day-ahead forecast for day D is made on the morning of D-1. A lag of 24 hours would use D-1's evening load, which does not exist yet at that time, and would flatter the model against Transelectrica's real forecast. The same goes for using measured temperature in training when only a forecast is available in production.

**Decision.** Load lags start at 48 hours (48, 168, 336 and the mean of four weeks). Temperature is Open-Meteo's forecast issued 48 hours before each hour (Previous Runs API), population-weighted over 8 cities; training and serving use the same column. The live forecast for D is trained only on data before D-1 00:00. The backtest refits monthly on an expanding window.

**Consequences.** Scores are slightly worse than a leaky setup would show, and honest. `tests/test_ml_features.py` fails if any feature uses the last 48 hours.
