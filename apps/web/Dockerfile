# Multi-stage, non-root (D15 image discipline), matching the API and ml-service images.
#
# Build context is the REPO ROOT, like the other services, so paths below are repo-relative.
#
# The build sets BUILD_STANDALONE=1, which is the ONLY place standalone output is enabled.
# It is opt-in because `next start` refuses to run against a standalone build, which made
# the local `pnpm preview` (next build && next start) an unsupported combination. Deployment
# wants standalone; local development wants a normal build. See apps/web/next.config.ts.

# ---- deps ----------------------------------------------------------------------------
# Separate stage so a source-only change does not re-resolve the dependency tree.
FROM node:22-slim AS deps
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ---- builder -------------------------------------------------------------------------
FROM node:22-slim AS builder
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1 BUILD_STANDALONE=1
RUN corepack enable
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./

# The API address is server-only (src/lib/env.ts) and never reaches the browser bundle
# (D23), so it stays a runtime setting and one image still serves every environment for
# everything except the line below.
#
# CLERK IS THE ONE EXCEPTION, and it is not a choice we get to make. Next INLINES
# NEXT_PUBLIC_* into the client bundle at build time, and `/` is statically prerendered —
# so the server component that decides whether to mount ClerkProvider also runs here, at
# build. Supplying the key at runtime through `env_file` therefore does NOTHING: the HTML
# is already generated and the bundle already holds an empty string. It fails SILENTLY,
# which is what makes it worth this much comment — the container starts, the page renders,
# and the sign-in button is simply absent with nothing in any log to say why.
#
# The publishable key is public by design (it ships to every browser), so baking it costs
# no secrecy. What it costs is portability: an image built with one Clerk instance's key
# serves that instance only. That is the actual trade, and it is Clerk's to impose.
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=""
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
RUN pnpm build

# ---- runtime -------------------------------------------------------------------------
FROM node:22-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

# Standalone emits a self-contained server plus only the modules actually imported. Static
# assets are NOT included in it and must be copied alongside, or every page renders unstyled
# with no JS — a failure that looks like a broken app rather than a missing COPY.
COPY --from=builder --chown=appuser:appuser /app/.next/standalone ./
COPY --from=builder --chown=appuser:appuser /app/.next/static ./.next/static

# Same reasoning as P6.1.5 dropping pip from the API runtime: nothing installs packages
# here — the builder resolved everything — so removing npm and corepack removes both the
# finding and the capability. A runtime that cannot fetch packages is a smaller target
# than one that merely should not.
USER root
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx \
    /usr/local/bin/corepack /usr/local/lib/node_modules/corepack

USER appuser
EXPOSE 3000

# node's own http client: this image has no curl or wget, and adding one to satisfy a probe
# would put a network tool back into a runtime we just finished stripping.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
