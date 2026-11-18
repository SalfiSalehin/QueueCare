FROM node:22-alpine AS base
WORKDIR /app

FROM base AS dev
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json* ./
# Reproducible installs: with a committed package-lock.json use exactly what it pins (npm ci); without one, resolve fresh.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
# Create the folders that compose mounts volumes over, owned by `node`. Without this Docker creates them as root
# and `next dev` dies with EACCES when it tries to write .next/cache.
RUN mkdir -p /app/.next /app/node_modules && chown -R node:node /app
USER node
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

# ---- Production image -------------------------------------------------------------------------------------------
# docker compose -f docker-compose.prod.yml build frontend   (needs internet at build time: npm and Google Fonts)
FROM base AS build
ENV NEXT_TELEMETRY_DISABLED=1
# Baked into the browser bundle at build time. Same-origin by default: the reverse proxy sends /api/* to the API.
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ARG NEXT_PUBLIC_WS_URL=
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
COPY package.json package-lock.json* ./
# Reproducible installs: with a committed package-lock.json use exactly what it pins (npm ci); without one, resolve fresh.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# `output: "standalone"` copies only what the server needs, so the image carries no dev dependencies or source.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
