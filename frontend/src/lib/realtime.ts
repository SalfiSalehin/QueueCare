// Live updates over WebSocket. The server sends "something changed" hints; the UI refetches over REST.
// This file has no React in it so the protocol handling can be unit-tested with a fake socket.
import type { RealtimeMessage } from "@/types/api";

export type LiveStatus = "connecting" | "live" | "offline";

/** Exponential back-off with a cap and +/-20% jitter. `random` is injectable for tests. */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1_000 * 2 ** Math.max(0, attempt));
  return Math.round(base * (0.8 + random() * 0.4));
}

/** Parse one server frame. Unknown or malformed frames return null (ignored, never thrown). */
export function parseMessage(raw: unknown): RealtimeMessage | null {
  if (typeof raw !== "string") return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (typeof value !== "object" || value === null) return null;
  const m = value as Record<string, unknown>;
  switch (m.type) {
    case "ready": case "pong": case "resync":
      return { type: m.type };
    case "event":
      if (typeof m.id === "string" && typeof m.event === "string") {
        return {
          type: "event", id: m.id, event: m.event, version: typeof m.version === "number" ? m.version : 0,
          ts: typeof m.ts === "string" ? m.ts : "", data: typeof m.data === "object" && m.data !== null ? (m.data as Record<string, unknown>) : {},
        };
      }
      return null;
    default:
      return null;
  }
}

/** Delivery is at-least-once, so remember recent event ids and drop repeats. Bounded memory. */
export class Deduper {
  private seen = new Set<string>();
  constructor(private readonly limit = 500) {}
  /** True the first time an id is seen. */
  first(id: string): boolean {
    if (this.seen.has(id)) return false;
    this.seen.add(id);
    if (this.seen.size > this.limit) {
      const oldest = this.seen.values().next().value;
      if (oldest !== undefined) this.seen.delete(oldest);
    }
    return true;
  }
}

/** Build the socket URL from the ticket response. A WebSocket cannot go through the Next dev proxy, so in
 *  development NEXT_PUBLIC_WS_URL points at the API origin; behind the production reverse proxy it is empty and
 *  the page's own origin is used. Only the origin of NEXT_PUBLIC_WS_URL is used: the path comes from the server. */
export function socketUrl(ticket: string, path: string, configured: string | undefined, page: { protocol: string; host: string }): string {
  let origin: string;
  if (configured) {
    const u = new URL(configured);
    origin = `${u.protocol}//${u.host}`;
  } else {
    origin = `${page.protocol === "https:" ? "wss:" : "ws:"}//${page.host}`;
  }
  return `${origin}${path}?ticket=${encodeURIComponent(ticket)}`;
}

export interface SocketLike {
  onopen: (() => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export interface RealtimeDeps {
  fetchTicket: () => Promise<{ ticket: string; websocket_path: string }>;
  createSocket: (ticket: string, path: string) => SocketLike;
  /** Called for each distinct event and for connect/reconnect/resync (state may have been missed). */
  onChange: (reason: "event" | "resync" | "connected") => void;
  onStatus: (s: LiveStatus) => void;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (id: unknown) => void;
  random?: () => number;
  pingEveryMs?: number;
}

/** Connects with a fresh single-use ticket, pings to stay under the server's idle timeout, and reconnects with
 *  back-off. Never throws: failures just move the status to "offline" so the UI falls back to polling. */
export class RealtimeClient {
  private socket: SocketLike | null = null;
  private attempt = 0;
  private stopped = true;
  private retryTimer: unknown = null;
  private pingTimer: unknown = null;
  private readonly dedupe = new Deduper();
  private readonly setTimer: (fn: () => void, ms: number) => unknown;
  private readonly clearTimer: (id: unknown) => void;

  constructor(private readonly deps: RealtimeDeps) {
    this.setTimer = deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = deps.clearTimer ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>));
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const s = this.socket;
    this.socket = null;
    if (s) { s.onopen = s.onmessage = s.onclose = s.onerror = null; s.close(); }
  }

  private clearTimers(): void {
    if (this.retryTimer !== null) this.clearTimer(this.retryTimer);
    if (this.pingTimer !== null) this.clearTimer(this.pingTimer);
    this.retryTimer = this.pingTimer = null;
  }

  private async connect(): Promise<void> {
    this.deps.onStatus("connecting");
    try {
      const { ticket, websocket_path } = await this.deps.fetchTicket();
      if (this.stopped) return;
      const s = this.deps.createSocket(ticket, websocket_path);
      this.socket = s;
      s.onmessage = (ev) => this.handle(parseMessage(ev.data));
      s.onclose = () => this.lost(s);
      s.onerror = () => { /* onclose follows; handled there */ };
    } catch {
      if (!this.stopped) this.scheduleRetry();
    }
  }

  private handle(msg: RealtimeMessage | null): void {
    if (!msg) return;
    if (msg.type === "ready") {
      this.attempt = 0;
      this.deps.onStatus("live");
      this.deps.onChange("connected");          // refetch first, then continue with the stream
      this.startPing();
    } else if (msg.type === "resync") {
      this.deps.onChange("resync");
    } else if (msg.type === "event" && this.dedupe.first(msg.id)) {
      this.deps.onChange("event");
    }
  }

  private startPing(): void {
    const every = this.deps.pingEveryMs ?? 30_000;
    const tick = () => {
      if (this.stopped || !this.socket) return;
      try { this.socket.send(JSON.stringify({ type: "ping" })); } catch { /* close handler will follow */ }
      this.pingTimer = this.setTimer(tick, every);
    };
    this.pingTimer = this.setTimer(tick, every);
  }

  private lost(s: SocketLike): void {
    if (this.stopped || this.socket !== s) return;
    this.socket = null;
    this.clearTimers();
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    this.deps.onStatus("offline");
    const delay = backoffDelay(this.attempt++, this.deps.random);
    this.retryTimer = this.setTimer(() => { void this.connect(); }, delay);
  }
}
