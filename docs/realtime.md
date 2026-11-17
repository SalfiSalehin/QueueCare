# Real-time protocol (Phase 6)

Queue and appointment changes are pushed to browsers over a WebSocket. The design goal is that a
committed change is **never lost** and a client can **always recover** by re-reading state over REST.

## Pipeline

```
service (one DB transaction)
  UPDATE queue/appointment  +  INSERT outbox_events        <- same commit, or neither
        |
relay (app/workers/outbox_relay.py): lock unpublished rows (FOR UPDATE SKIP LOCKED) -> publish -> mark published
        |
broker: Redis Pub/Sub (REDIS_URL set)  or  in-memory (single process)
        |
hub (app/websocket/hub.py): per-process registry -> only the connections subscribed to that channel
        |
browser WebSocket
```

* **Transactional outbox.** `emit()` adds a row to the caller's transaction. If the business change rolls back, so does the event.
* **At-least-once.** The relay publishes, then marks `published_at`. A crash in between re-publishes later: duplicates are possible, losses are not. Every event has a stable `id`.
* **Several API replicas** can each run a relay: `SKIP LOCKED` prevents double work. Redis lets any replica's event reach clients connected to any other replica.
* **Redis is transient.** The durable record is the outbox row. After the Redis listener reconnects, connected clients receive `{"type":"resync"}`.
* Published rows are deleted after `OUTBOX_RETENTION_DAYS` (default 7).

## Connecting

1. `POST /api/v1/clinics/{clinic_id}/realtime/ticket` (cookie session + `X-CSRF-Token`, any active member) returns `{ticket, expires_in: 30}`.
2. Open `wss://<host>/api/v1/ws?ticket=<ticket>`.

A ticket lives 30 s, is bound to one user, clinic and login session, and works once. It proves identity only; the role and channels are derived from the database when you connect. It is signed with a key derived from `JWT_SECRET` that differs from the access-token key, so neither token type is valid as the other.

The handshake is refused (HTTP 403) for: a missing, malformed, expired, reused or foreign ticket; a revoked session; a user or membership that is no longer active; a clinic that is not ACTIVE; an `Origin` header that is not in `BACKEND_CORS_ORIGINS`; or too many connections (per user `WS_MAX_CONNECTIONS_PER_USER`, per address `WS_MAX_CONNECTIONS_PER_IP`).

While connected, the session and membership are re-checked every `WS_REVALIDATE_SECONDS` (default 300). If access was revoked or the role changed, the server closes with code 1008 and the client must fetch a new ticket.

## Channels (chosen by the server, never by the client)

| Channel | Who receives it |
|---|---|
| `clinic:{cid}:staff` | clinic admins and receptionists: every queue and appointment change in the clinic |
| `clinic:{cid}:doctor:{did}` | the doctor whose profile is `did`: their own queue and appointments |
| `clinic:{cid}:user:{uid}` | that user only: their own token position and appointment status |

Every channel starts with `clinic:{cid}:`, so one clinic's events can never match another clinic's connection. `emit()` also refuses a channel that does not belong to the event's clinic.

## Messages

Server to client:

```json
{"type":"ready"}
{"type":"event","id":"<uuid>","event":"queue.updated","version":123,"ts":"2030-01-07T09:00:00+00:00","data":{...}}
{"type":"resync"}
{"type":"pong"}
```

Client to server: only `{"type":"ping"}`. Anything else (including an attempt to subscribe to a channel), invalid JSON, or a message over 256 characters closes the connection.

| `event` | Sent to | `data` |
|---|---|---|
| `queue.updated` | staff, doctor | `doctor_id, token_id, token_label, status, token_version, change` |
| `queue.position` | a patient with an account who is in that doctor's queue today | `token_id, token_label, doctor_id, status, people_ahead, token_version` (their own token only) |
| `appointment.updated` | staff, doctor, the booking patient | `appointment_id, doctor_id, status, starts_at, change` |

Payloads never contain patient names, phone numbers or any clinical data.

## What a client must do

1. **Deduplicate on `id`** (delivery is at-least-once).
2. Treat events as **"something changed" hints**: refetch the relevant REST resource (`/doctors/{id}/queue`, `/queue/mine`, `/appointments`). For `queue.position`, ignore an event whose `token_version` is lower than one already applied for that token.
3. **Do not use the global `version` to drop events.** It comes from a database sequence assigned at INSERT time, so two concurrent transactions can commit in the opposite order to their numbers. The relay publishes committed rows in `version` order, but a lower number can legitimately arrive after a higher one.
4. On connect, reconnect or `resync`: **refetch state over REST first**, then continue with the stream. Reconnect with a new ticket and exponential back-off. A slow client is disconnected with 1013 instead of buffering without limit, so it will reconnect and resync.
5. Send a `ping` at least every `WS_IDLE_TIMEOUT_SECONDS` (default 90) or the server closes the idle connection.

## Operating notes and known limits

* Without `REDIS_URL` the in-memory broker only works inside one process (fine for local development and the test suite). Production with more than one API process needs Redis.
* The relay runs inside the API process (`OUTBOX_RELAY_ENABLED=true`). Run it in a separate worker later if API load requires it.
* Per change, patient events are capped at 200 recipients (`MAX_PATIENT_FANOUT`); patients beyond that rely on REST polling.
* The ticket travels in the query string, which proxies and access logs may record. It is single-use and expires in 30 s, so a logged ticket is useless.
* If Redis is unreachable, ticket single-use falls back to a per-process check (logged as a warning), mirroring the rate limiter.
* Not built yet: the browser client (Phase 3-5 frontend track), live wait-time estimates (Phase 7), notifications (Phase 8).

## Testing note: WebSocket teardown race (found in Phase 7 runs)
Starlette 1.10's test client, on leaving a `websocket_connect` block, sends "disconnect" and immediately
cancels the server task without waiting for it. When the gateway was still cleaning up, the cancellation
escaped and a random WebSocket test failed with `CancelledError` (a different one each run). Two changes:
the gateway's `finally` now unregisters the connection synchronously first and tolerates being cancelled
again while it finishes; and the tests use a `connect()` helper that sends the disconnect, waits (bounded)
for the server to unregister, and only then lets the client tear down. Production servers do not cancel
handlers this way; the gateway change only makes shutdown cleanup harder to interrupt.
