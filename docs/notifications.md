# Notifications (Phase 8)

> Providers are **mocks**: no email or SMS ever leaves the system. They record messages in memory so the
> whole pipeline (creation, retries, idempotency) is real and testable without sending anything.

## What is sent, to whom

| Type | Trigger | Recipient |
|---|---|---|
| `appointment.booked` / `confirmed` / `cancelled` / `rescheduled` | the matching appointment action | the patient (only if the patient has an account) |
| `appointment.reminder` | worker scan: confirmed appointments starting within 24 h (`NOTIFICATION_REMINDER_HOURS`) | the patient |
| `queue.called` | a token is called ("It's your turn") | the patient |

Channels per notification: **IN_APP** always; **EMAIL** only to a *verified* address; **SMS** only for the
time-critical types (reminder, "your turn") and only if the user has a phone number. There is no phone
verification or consent record yet, so SMS is deliberately limited. Patients without an account are not
notified (the row needs a user).

Message text (`notification_templates.py`) carries the minimum: clinic, doctor, time in the clinic's time
zone, or the token label. No diagnosis or medical detail, no other patient's identity.

## How it works

1. **Creation is transactional.** `enqueue()` runs inside the caller's transaction, so a notification exists
   if and only if the change that caused it committed. It is wrapped in a savepoint: if enqueueing itself
   fails, the booking/queue action still succeeds (the failure is logged). Trade-off: a bug there means a
   missing notification rather than a failed booking.
2. **Idempotent.** `idempotency_key = type : entity : version : user : channel` is UNIQUE and inserts use
   `ON CONFLICT DO NOTHING`, so repeating an enqueue (a retry, a rescan) never duplicates. Calling the same
   token twice produces two notifications because the key includes the token version.
3. **Delivery worker** (`workers/notification_worker.py`, started with the API; disabled in tests):
   - *Claim*: lock due rows (`FOR UPDATE SKIP LOCKED`), set a lease (`next_attempt_at = now + 120 s`),
     increment `attempts`, commit. Concurrent workers never pick the same row.
   - *Deliver* each claimed row without holding locks; on success `SENT`.
   - *Retry* with exponential back-off (30 s, 60 s, 120 s, 240 s; capped at 1 h) up to `NOTIFICATION_MAX_ATTEMPTS`
     (5), then `FAILED` with the reason. A permanent provider error fails at once.
   - A worker that dies mid-batch leaves a lease; the row is claimed again after it expires. The attempt
     counter already includes the lost try, so a row that keeps killing workers ends `FAILED`
     ("attempts exhausted") instead of looping forever.
   - A reminder whose appointment is no longer `CONFIRMED` at send time is dropped (`FAILED`, "skipped...").
   - Only the error text of our own `ProviderError` is stored; for any other exception only its class name
     is stored, because arbitrary exception text can contain addresses.
4. **Reminders**: every 5 minutes the worker scans for confirmed appointments in the next 24 h and enqueues a
   reminder per appointment (key includes the start time), so rescans are no-ops.
5. **Retention**: finished rows (`SENT`, `READ`, `FAILED`) older than 30 days are purged hourly. `PENDING` rows are kept.

## Delivery guarantee

**At least once, never silently lost.** A crash between "provider accepted" and "marked SENT" can make the
provider see the same message twice. The notification's idempotency key is passed to the provider so a
provider that supports idempotent sends can drop the duplicate. The mock does not dedupe (so tests can detect duplicates).

## In-app inbox API

All under `/api/v1/clinics/{cid}/notifications`, any clinic member, **own notifications only** (another
member's notification is a 404): `GET ""` (`?unread=true`, paging), `GET /unread-count`, `POST /{id}/read`,
`POST /read-all`.

## Known limitations

- Mock providers only; no real email/SMS provider, bounce handling or webhooks.
- No per-user notification preferences or opt-out yet.
- No phone verification, so SMS is limited to reminders and "your turn".
- Staff (doctors, receptionists) are not notified of anything yet; only patients.
- In-app notifications are pulled (fetched), not pushed over the WebSocket gateway; wiring them to the real-time channel is a later improvement.
- The reminder scan reads all upcoming confirmed appointments of all clinics every 5 minutes (capped at 500 per scan). Fine for a demo, would need paging/indexing at scale.
