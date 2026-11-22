/** @type {import('next').NextConfig} */
const apiInternal = (process.env.API_INTERNAL_URL || "http://backend:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,                 // hides the round "N" badge the dev server draws over the page corner (it covered the sidebar and footer)
  poweredByHeader: false,
  output: "standalone",                 // small production image (see Dockerfile, stage `prod`)
  // The browser only ever talks to this origin. /api/v1/* is proxied to the backend, so session cookies are
  // same-origin and the CSRF cookie is readable. In production Caddy does this routing instead (see Caddyfile).
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiInternal}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
