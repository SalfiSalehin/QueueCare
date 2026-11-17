import net from "node:net";

/**
 * The browser in the test container opens the live-updates WebSocket at ws://localhost:8000 (that is what the dev
 * frontend is configured with). In this container nothing listens there, so forward it to the API container.
 * Returns a function that stops the forwarder. If the port is already taken, does nothing.
 */
export function startForward(listenPort: number, targetHost: string, targetPort: number): Promise<() => Promise<void>> {
  return new Promise((resolve) => {
    const sockets = new Set<net.Socket>();
    const server = net.createServer((client) => {
      const upstream = net.connect(targetPort, targetHost);
      sockets.add(client); sockets.add(upstream);
      const drop = () => { client.destroy(); upstream.destroy(); sockets.delete(client); sockets.delete(upstream); };
      client.on("error", drop); upstream.on("error", drop); client.on("close", drop); upstream.on("close", drop);
      client.pipe(upstream); upstream.pipe(client);
    });
    server.once("error", () => resolve(async () => undefined));       // port in use: nothing to forward or stop
    server.listen(listenPort, "127.0.0.1", () =>
      resolve(() => new Promise<void>((done) => { sockets.forEach((s) => s.destroy()); server.close(() => done()); })));
  });
}
