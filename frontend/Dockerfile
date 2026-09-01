# syntax=docker/dockerfile:1.7
# ------------------------------------------------------------------- deps
FROM node:22-alpine AS deps
WORKDIR /app

# Install against the lockfile only, so this layer is cached until dependencies change.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ------------------------------------------------------------------ build
FROM node:22-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined at build time, so the API URL must be known here.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
# Opts next.config.mjs into `output: 'standalone'`, which the runtime stage below copies.
# Vercel builds the same source without this and uses its own output format instead.
ENV BUILD_STANDALONE=true

RUN npm run build

# ---------------------------------------------------------------- runtime
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# `output: 'standalone'` traces exactly the files the server needs, so the runtime image
# carries neither the full node_modules nor the build toolchain.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
