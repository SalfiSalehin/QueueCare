"""Wall-clock smoke test against a RUNNING stack (synthetic data only). Prints measured latencies; asserts nothing.

    docker compose up -d
    python scripts/perf_smoke.py --base http://localhost:8000 --email you@example.com --password '...' --clinic <uuid>

Uses only the standard library. Numbers depend on your machine; record them as measured, with the hardware, and
never present them as a production benchmark. Writes nothing to the database except through normal read endpoints.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

ENDPOINTS = ["/auth/me", "/clinics/{c}/doctors", "/clinics/{c}/queue/mine", "/clinics/{c}/analytics/overview"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--clinic", required=True)
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()
    if not a.base.startswith(('http://', 'https://')):
        ap.error('--base must start with http:// or https://')

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    req = urllib.request.Request(f"{a.base}/api/v1/auth/login", method="POST",  # noqa: S310 - scheme validated above
                                 data=json.dumps({"email": a.email, "password": a.password}).encode(),
                                 headers={"Content-Type": "application/json", "Origin": "http://localhost:3000"})
    opener.open(req).read()  # noqa: S310 - scheme validated above
    print(f"{'endpoint':45} {'n':>4} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}  statuses")
    for path in ENDPOINTS:
        url = f"{a.base}/api/v1{path.format(c=a.clinic)}"
        times, codes = [], {}
        for _ in range(a.n):
            t0 = time.perf_counter()
            try:
                code = opener.open(url).status  # noqa: S310 - scheme validated above
            except urllib.error.HTTPError as e:
                code = e.code
            times.append((time.perf_counter() - t0) * 1000)
            codes[code] = codes.get(code, 0) + 1
        times.sort()
        p95 = times[max(0, int(len(times) * 0.95) - 1)]
        print(f"{path:45} {len(times):>4} {statistics.median(times):>8.1f} {p95:>8.1f} {times[-1]:>8.1f}  {codes}")


if __name__ == "__main__":
    main()
