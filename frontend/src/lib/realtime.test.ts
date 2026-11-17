import { describe, expect, it } from "vitest";
import { backoffDelay, Deduper, parseMessage, RealtimeClient, socketUrl, type LiveStatus, type SocketLike } from "@/lib/realtime";

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closed = false;
  send(d: string) { this.sent.push(d); }
  close() { this.closed = true; }
  receive(obj: unknown) { this.onmessage?.({ data: typeof obj === "string" ? obj : JSON.stringify(obj) }); }
}

function harness() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number; id: number }[] = [];
  const statuses: LiveStatus[] = [];
  const changes: string[] = [];
  let tickets = 0;
  let nextId = 1;
  const client = new RealtimeClient({
    fetchTicket: async () => ({ ticket: `t${++tickets}`, websocket_path: "/api/v1/ws" }),
    createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s; },
    onChange: (r) => changes.push(r),
    onStatus: (s) => statuses.push(s),
    setTimer: (fn, ms) => { const id = nextId++; timers.push({ fn, ms, id }); return id; },
    clearTimer: (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); },
    random: () => 0.5,
  });
  const flush = () => new Promise((r) => setTimeout(r, 0));
  return { client, sockets, timers, statuses, changes, flush, tickets: () => tickets };
}

describe("backoffDelay", () => {
  it("doubles up to a 30 s cap", () => {
    const d = (n: number) => backoffDelay(n, () => 0.5);
    expect([d(0), d(1), d(2), d(3)]).toEqual([1000, 2000, 4000, 8000]);
    expect(d(10)).toBe(30_000);
  });
  it("stays within +/-20% jitter", () => {
    expect(backoffDelay(2, () => 0)).toBe(3200);
    expect(backoffDelay(2, () => 1)).toBe(4800);
  });
});

describe("parseMessage", () => {
  it("accepts protocol frames and rejects junk", () => {
    expect(parseMessage('{"type":"ready"}')).toEqual({ type: "ready" });
    expect(parseMessage('{"type":"resync"}')).toEqual({ type: "resync" });
    expect(parseMessage('{"type":"event","id":"e1","event":"queue.updated","version":3,"ts":"x","data":{"a":1}}'))
      .toMatchObject({ type: "event", id: "e1", event: "queue.updated", data: { a: 1 } });
    for (const bad of ["not json", "[]", "null", '{"type":"event"}', '{"type":"nope"}', 5, undefined]) {
      expect(parseMessage(bad)).toBeNull();
    }
  });
});

describe("Deduper", () => {
  it("reports an id once and stays bounded", () => {
    const d = new Deduper(2);
    expect(d.first("a")).toBe(true);
    expect(d.first("a")).toBe(false);
    d.first("b"); d.first("c");           // evicts "a"
    expect(d.first("a")).toBe(true);
  });
});

describe("socketUrl", () => {
  const page = { protocol: "https:", host: "clinic.example" };
  it("uses the page origin when nothing is configured, and wss for https", () => {
    expect(socketUrl("a b", "/api/v1/ws", undefined, page)).toBe("wss://clinic.example/api/v1/ws?ticket=a%20b");
  });
  it("uses only the origin of the configured URL; the path comes from the server", () => {
    expect(socketUrl("t", "/api/v1/ws", "ws://localhost:8000/ws", page)).toBe("ws://localhost:8000/api/v1/ws?ticket=t");
  });
});

describe("RealtimeClient", () => {
  it("goes live on ready, refetches once, and pings", async () => {
    const h = harness();
    h.client.start();
    await h.flush();
    expect(h.statuses).toEqual(["connecting"]);
    h.sockets[0]?.receive({ type: "ready" });
    expect(h.statuses).toEqual(["connecting", "live"]);
    expect(h.changes).toEqual(["connected"]);
    const ping = h.timers.find((t) => t.ms === 30_000);
    ping?.fn();
    expect(h.sockets[0]?.sent).toEqual(['{"type":"ping"}']);
  });

  it("signals a change once per distinct event id and on resync", async () => {
    const h = harness();
    h.client.start();
    await h.flush();
    const s = h.sockets[0];
    s?.receive({ type: "ready" });
    const ev = { type: "event", id: "e1", event: "queue.updated", version: 1, ts: "", data: {} };
    s?.receive(ev); s?.receive(ev); s?.receive({ ...ev, id: "e2" });
    s?.receive({ type: "resync" });
    s?.receive("garbage");
    expect(h.changes).toEqual(["connected", "event", "event", "resync"]);
  });

  it("goes offline when the socket closes, then reconnects with a NEW ticket", async () => {
    const h = harness();
    h.client.start();
    await h.flush();
    h.sockets[0]?.receive({ type: "ready" });
    h.sockets[0]?.onclose?.();
    expect(h.statuses.at(-1)).toBe("offline");
    const retry = h.timers.find((t) => t.ms === 1000);
    expect(retry).toBeDefined();
    retry?.fn();
    await h.flush();
    expect(h.tickets()).toBe(2);
    expect(h.sockets).toHaveLength(2);
  });

  it("stop() closes the socket and prevents reconnects", async () => {
    const h = harness();
    h.client.start();
    await h.flush();
    const s = h.sockets[0];
    s?.receive({ type: "ready" });
    h.client.stop();
    expect(s?.closed).toBe(true);
    s?.onclose?.();
    expect(h.timers).toHaveLength(0);
    expect(h.tickets()).toBe(1);
  });

  it("falls back to offline and retries when the ticket request fails", async () => {
    const statuses: LiveStatus[] = [];
    const timers: number[] = [];
    const client = new RealtimeClient({
      fetchTicket: async () => { throw new Error("401"); },
      createSocket: () => { throw new Error("unused"); },
      onChange: () => undefined, onStatus: (s) => statuses.push(s),
      setTimer: (_fn, ms) => { timers.push(ms); return 1; }, clearTimer: () => undefined, random: () => 0.5,
    });
    client.start();
    await new Promise((r) => setTimeout(r, 0));
    expect(statuses).toEqual(["connecting", "offline"]);
    expect(timers).toEqual([1000]);
  });
});
