<p align="right"><a href="README.md"><img src="docs/flags/fr.svg" width="20" alt=""> Français</a> · <img src="docs/flags/en.svg" width="20" alt=""> <strong>English</strong></p>

# ollama-gateway — Ollama API-key management gateway

> **Interface fully translated into the 24 official languages of the European Union.**

## Showcase

<p align="center">
  <a href="docs/showcase/showcase.mp4"><img src="docs/showcase/showcase.gif" alt="ollama-gateway demo" width="480"></a>
  <br><em><a href="docs/showcase/showcase.mp4">Watch the HD demo with sound (mp4)</a></em>
</p>

An authentication gateway in front of one or more Ollama servers: **per-client API keys**, **origin
restriction** (IP/CIDR), **quotas** (monthly token cap + rate-limit), **execution servers** (local +
remote, one key ↦ one server, schema-agnostic model restriction), **usage logging**, and a
**LAN-only web admin panel**. Public-domain TLS is terminated by **Caddy** (ACME DNS-01 Scaleway
challenge — no inbound port required beyond the one already forwarded).

It replaces the old single-key nginx reverse proxy and proxies the **inference and read** endpoints
(`/api/*`, `/v1/*`), streaming (NDJSON/SSE), stripping the client key before the upstream. The
**catalog-management** endpoints (`pull`/`push`/`delete`/`create`/`copy`/`blobs`) are **never**
proxied (403) — model management happens from the admin console.

## Overview

| | |
|---|---|
| ![Dashboard](app/static/manual/01-dashboard.jpg) | ![Key usage charts](app/static/manual/27-key-charts.jpg) |
| **Dashboard** — keys, quotas, creation | **Key detail** — charts (horizons, values), per-model usage |
| ![Servers & compatibility](app/static/manual/06-servers.jpg) | ![Server monitoring](app/static/manual/17-monitor.jpg) |
| **Execution servers** + API compatibility matrix | **Monitoring** — consumption, statuses, per key and per model |

## Features

- **Per-client API keys** — hashed (sha-256), secret shown **only once**, revocable.
- **Per-key origin restriction** (IP/CIDR, resistant to `X-Forwarded-For` spoofing).
- **Quotas** — monthly token cap + rate-limit (req/min), plus absolute "lifetime" caps/expiry
  (cost-capped trials).
- **Multiple execution servers** — local + remote (token encrypted at rest), one key ↦ one server,
  automatic **fallback server** on 5xx/connection failure.
- **Per-key model and API restriction** — schema-agnostic (native Ollama, OpenAI, Anthropic),
  listing filtering; **image generation** as a separate capability.
- **Catalog management** (pull / delete models) from the console — **never** exposed to clients
  (the proxy rejects `pull`/`delete`/… with 403).
- **Logging & monitoring** — per-request usage, **time-series charts** (horizons 24 h → 3 months,
  axis scales, per-point values), **per-model usage**, full request-content viewer (grep), origin
  banning.
- **LAN-only, server-rendered admin panel**, **24 EU languages**, P2Enjoy design system.
- **Caddy TLS edge** (ACME DNS-01, no inbound port required), fully **dockerized** (self-seeded dev,
  `network_mode: host` prod) with a **pre-deploy security gate**.

💡 **Built-in online manual** — to ease onboarding, the panel embeds an **illustrated manual**
(the **"Manual"** navigation button) that explains each screen with a real screenshot of the
application. Public source: [docs/manual.md](docs/manual.md).

## Architecture

```
External client ──https──► Caddy (TLS DNS-01) ──► proxy (auth/origin/quota/usage) ──► Ollama 127.0.0.1:11434
                                                        │
Admin (LAN) ──http──► admin (login) ── SQLite (WAL) ───┘
```

- **proxy** (`app/proxy.py`) — exposed via Caddy, loopback-bound. Validates `Authorization: Bearer
  <key>`, checks origin and quotas, logs, relays streaming, strips the key.
- **admin** (`app/admin.py`) — bound to the LAN IP only, password login, key CRUD + dashboard.
- **SQLite** shared (WAL) between the two roles.

See [docs/DAT.md](docs/DAT.md) for details (services, data, launch, deployment) and
[docs/manual.md](docs/manual.md) for the public functional manual.

## Run in dev (self-contained, self-seeded)

```bash
./runDev        # fake Ollama + proxy + admin ; SQLite re-seeded on each run
# Admin : http://localhost:8788/admin  (password: adminpass)
# Proxy : http://localhost:8787/_proxy_health
# Demo key : sk-ollama-devdemokey0000000000000000000000000000000000000000000000000
```

Test a proxied call:
```bash
curl -s http://localhost:8787/api/chat \
  -H "Authorization: Bearer sk-ollama-devdemokey000000000000000000000000000000000000000000000000" \
  -d '{"model":"demo:latest","stream":true}'
```

## Tests

```bash
# Unit + integration (Python)
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m pytest                       # unit + integration suite

# E2E (Playwright: admin UI + proxy), .jpg captures + .webm video in e2e/output/
cd e2e && npm install && npm test
```

## Staging / Prod

- `./runStaging` — full chain with Caddy (`tls internal`) + fake upstream, to validate routing/TLS
  locally (`https://localhost:8443/…`, `curl -k`).
- `./runProd` — on the prod host: Caddy (DNS-01 Scaleway) + proxy + admin in `network_mode: host`.
  Requires `.env.prod` (copy `.env.prod.example`). See [docs/DAT.md](docs/DAT.md) §Deployment.

## Security

- The client key is **hashed** (sha-256) in the database, never stored in clear; shown once at
  creation.
- The admin is **never** exposed by Caddy (only `/api/*`, `/v1/*`, `/_proxy_health` are) and binds
  to the LAN IP only.
- No secrets in the repo: `SCW_SECRET_KEY`, admin password, keys — everything lives in `.env` /
  the database, outside git (see `.gitignore`).
- **Fail-closed in prod**: refuses to start if a critical secret is missing/default, or if the admin
  role would bind to "all interfaces". Highly-random keys, remote tokens encrypted at rest (Fernet),
  same-origin CSRF + login anti-brute-force, security headers (HSTS/CSP), non-root container,
  digest-pinned base image.
- **Pre-deploy security gate**: `./runProd` runs `scripts/security-sweep.sh` (secrets, dependency
  CVEs, SAST, test suite) and **refuses to deploy** if anything is found.

## License

**Ollama Gateway is _source-available_, not OSI open-source**: the source is open and free to use,
but very-large-scale use is gated. Exact terms: [LICENSE.en.md](LICENSE.en.md).

- ✅ **Free** — use, modify, distribute and self-host, including in a company, **as long as all your
  instances (aggregated per entity) serve ≤ 1 billion tokens per month**.
- 💼 **Above the threshold** — a commercial license is required: **a one-time settlement fee of
  €29 excl. tax per installation**, unlimited use afterwards (e.g. 3 instances → €87 excl. tax).
  Write to **contact@p2enjoy.studio**, subject "Licence Ollama Gateway".
- 🔒 **Authorship** — keep the `LICENSE` file and attribution to the author: cloning the repo to
  strip the license is not permitted.
- 🤝 **On your honor** — **the software does not watch you**: no remote counting, no telemetry, no
  throttling. Compliance with the threshold rests entirely on your good faith. If you exceed it,
  play fair — it is what keeps the project open for everyone.

© 2026 Martino Bettucci — P2Enjoy SAS.
