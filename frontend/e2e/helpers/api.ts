import { request, type APIRequestContext } from "@playwright/test";
import { BASE_URL } from "./seed";

/** A browser-like API session: keeps cookies and echoes the CSRF cookie, exactly as the web app does. */
export class Session {
  private constructor(readonly ctx: APIRequestContext) {}

  static async create(): Promise<Session> {
    // Through the web app's own /api/v1 proxy, with the page's origin, so the same CORS/CSRF rules apply as in a browser.
    return new Session(await request.newContext({ baseURL: BASE_URL, extraHTTPHeaders: { Origin: BASE_URL } }));
  }

  private async csrf(): Promise<string | undefined> {
    return (await this.ctx.storageState()).cookies.find((c) => c.name === "qc_csrf")?.value;
  }

  async call<T = unknown>(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
    const csrf = await this.csrf();
    const res = await this.ctx.fetch(`/api/v1${path}`, {
      method,
      headers: csrf ? { "X-CSRF-Token": csrf } : {},
      data: body,
    });
    const text = await res.text();
    if (!res.ok()) throw new Error(`${method} ${path} -> ${res.status()}: ${text}`);
    return (text ? JSON.parse(text) : null) as T;
  }

  async saveState(file: string): Promise<void> {
    await this.ctx.storageState({ path: file });
  }

  async close(): Promise<void> {
    await this.ctx.dispose();
  }
}
