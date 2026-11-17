"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RealtimeClient, socketUrl, type LiveStatus, type SocketLike } from "@/lib/realtime";
import { queueService } from "@/services/queue";

/** Wraps the browser WebSocket in the small interface RealtimeClient uses (keeps the client testable). */
function openSocket(url: string): SocketLike {
  const ws = new WebSocket(url);
  const adapter: SocketLike = {
    onopen: null, onmessage: null, onclose: null, onerror: null,
    send: (d) => ws.send(d),
    close: () => ws.close(),
  };
  ws.onopen = () => adapter.onopen?.();
  ws.onmessage = (ev) => adapter.onmessage?.({ data: ev.data });
  ws.onclose = () => adapter.onclose?.();
  ws.onerror = () => adapter.onerror?.();
  return adapter;
}

/**
 * Keeps a live connection for one clinic and refetches the queue and appointment queries whenever the server
 * says something changed. Returns the connection status; screens poll faster while it is not "live".
 */
export function useRealtime(clinicId: string): LiveStatus {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    const client = new RealtimeClient({
      fetchTicket: () => queueService.ticket(clinicId),
      createSocket: (ticket, path) =>
        openSocket(socketUrl(ticket, path, process.env.NEXT_PUBLIC_WS_URL, window.location)),
      onStatus: setStatus,
      onChange: () => {
        void qc.invalidateQueries({ queryKey: ["board", clinicId] });
        void qc.invalidateQueries({ queryKey: ["day-appointments", clinicId] });
        void qc.invalidateQueries({ queryKey: ["my-queue", clinicId] });
        void qc.invalidateQueries({ queryKey: ["appointments", clinicId] });
      },
    });
    client.start();
    return () => client.stop();
  }, [clinicId, qc]);

  return status;
}
