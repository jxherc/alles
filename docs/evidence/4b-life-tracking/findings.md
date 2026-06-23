# stage 4b - life-tracking depth - audit findings (2026-06-23)

## current state
- the data is all there but inert: `JournalEntry.mood`, `Habit`/`HabitLog` (presence = done that day),
  `HealthEntry` (kind/date/value). there are NO statistics over them: no mood<->behavior correlation,
  no habit-failure prediction, no health baselines/anomaly bands. grep confirms no spearman/correlation/
  baseline helper anywhere.

## scope (highest-value testable cores)
1. mood -> behavior correlation: Spearman rank correlation + an explainable strength/direction label.
2. habit failure prediction: a risk score from the recent completion pattern.
3. health baselines + anomaly bands: mean/std baseline + z-score outlier flags.
DEFERRED: journal topic-threading (overlaps the recall index), task<->life balance synthesis + read-later
capacity planner (frontend dashboards).

## fix - new `services/life_stats.py` (pure)
- `spearman(xs, ys)` -> rank correlation rho (None if <3 points or no variance).
- `mood_score(s)` -> 1..5 from a mood word/emoji.
- `correlate(pairs)` -> {rho, n, strength, direction} (explainable).
- `habit_failure_risk(done_dates, today, window)` -> {risk, recent_rate, reason}.
- `health_baseline(values)` -> {mean, std, n}; `health_anomalies(series, k)` -> z-score outliers.
- routes: /life/correlate (mood vs a health metric), /habits/{id}/risk, /health/{kind}/anomalies.

tested: spearman +1/-1/too-few, mood ordering, correlate output, habit risk high/low, baseline mean/std,
anomaly flag + stable-none.
