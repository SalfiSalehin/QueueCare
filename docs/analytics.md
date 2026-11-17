# Clinic analytics (Phase 8)

Read-only aggregates for **clinic admins only** (`/api/v1/clinics/{cid}/analytics/...`). Counts and
statistics only: no patient names, contact details or identifiers appear in any response. Every query
filters on the clinic in context, and row-level security enforces the same boundary independently. A
member of another clinic gets 404. Dates (`start_date`, `end_date`, inclusive) are **clinic-local**; the
default is the last 30 days; the maximum range is 366 days.

| Endpoint | What it returns |
|---|---|
| `GET /overview` | appointment counts by status, no-show and cancellation rates, queue token counts, walk-in share, wait-time and consultation-length distributions (n, mean, p50, p90, max), a per-day series |
| `GET /doctors` | per doctor: scheduled minutes, booked minutes, consultation minutes, patients seen, average wait, two utilisation ratios |
| `GET /load` | arrivals by clinic-local hour (with average wait) and by weekday |
| `GET /prediction-accuracy` | per model version, for predictions whose real wait is now known: n, MAE, median absolute error, bias, interval coverage, and the naive-baseline MAE computed from the same rows |

## Definitions (so the numbers can be checked)

- **No-show rate** = NO_SHOW / (COMPLETED + NO_SHOW). **Cancellation rate** = CANCELLED / all appointments in range. Both are `null` (not 0%) when the denominator is 0.
- **Wait** = arrival to consultation start (`consultations.actual_wait_minutes`), for consultations started in the range. Percentiles use linear interpolation.
- **Scheduled minutes** = the doctor's weekly schedule rules (respecting `valid_from`/`valid_to`, overlapping rules merged) over the range in the clinic's time zone, **minus time off**.
- **Booked minutes** = non-cancelled appointments, including their buffer time. **Consultation minutes** = time actually spent in consultations.
- **Booked utilisation** = booked / scheduled; **busy utilisation** = consultation / scheduled. `null` when nothing was scheduled. Ratios are not clamped: values above 1 mean work outside scheduled hours.
- **Prediction bias** = mean(predicted median - actual): negative means the model under-predicts. `enough_data` is false below 30 completed predictions; below that the figures are anecdotes.

## Limitations

- Aggregation runs live in SQL on every request; there are no materialised views or caching (fine for a demo).
- Doctors cannot see their own analytics yet (admin only).
- Walk-in doctors without schedules show no utilisation ratio.
- Prediction accuracy reflects the synthetic-data model; it says nothing about a real clinic.
