# Deploy (free)

This API needs a **warm process** (in-memory model + OR-Tools). Sleeping PaaS free tiers (Render, etc.) wake slowly and rebuild cache on every cold start — a bad fit for `POST /plan`.

**Recommended $0 setup**

1. **GitHub Actions** — pytest, Gitleaks, pip-audit, Bandit, Ruff, Hadolint, Trivy (filesystem + image), CodeQL. Dependabot: `.github/dependabot.yml`. This does not host the API. 
2. **Oracle Cloud Always Free Ampere ARM VM** — always-on Linux. Run the Docker image there with a disk volume for `FPL_DATA_DIR`.
3. **Front-end later** — Cloudflare Pages or GitHub Pages (static, free). Set `FPL_CORS_ORIGINS` to that HTTPS origin.

Fly.io and paid Render are nicer PaaS, but they are not free for a 1GB always-on box.

## Local Docker

```text
cp .env.example .env
# edit FPL_SYNC_TOKEN
docker compose up --build
```

API: http://127.0.0.1:8000/docs

## Oracle Cloud Always Free (always-on)

1. Create an Oracle Cloud account and an **Ampere A1** VM (Ubuntu) in the Always Free shapes. Assign a public IP. Open **ingress TCP 8000** (or 80/443 if you add Caddy) in the VCN security list **and** `iptables`/`firewalld` on the VM if enabled.
2. SSH in, install Docker Engine + the Compose plugin ([Docker’s Ubuntu docs](https://docs.docker.com/engine/install/ubuntu/)).
3. Clone this repo (or `git pull` on deploy):

```bash
git clone https://github.com/zchaarim/fpl-radar-backend.git
cd fpl-radar-backend
cp .env.example .env
nano .env   # FPL_SYNC_TOKEN, later FPL_CORS_ORIGINS=https://your-pages-domain
docker compose up -d --build
```

4. First request to `/v1/status` or `POST /v1/sync` (header `X-Sync-Token`) warms FPL + Understat into the Docker volumes (`fpl-cache`, `fpl-understat`). Later restarts reuse that cache. Name mappings stay in the image (`data/mappings`).
5. Optional HTTPS without opening 443: [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (free) in front of `localhost:8000`.

Update:

```bash
cd fpl-radar-backend
git pull
docker compose up -d --build
```

Give the VM **at least ~1–2 GB RAM** for pandas + OR-Tools. The Ampere free allowance is far above that if the account quota is granted.

## What not to use for this API

- **GitHub Actions** as a 24/7 server (jobs die when the workflow ends).
- **Render/Railway free sleep** unless you only poke the API rarely and accept a ~1 minute wake plus a cold `ModelContext`.
- **256MB Fly machines** — too small; Fly also has no ongoing free tier for new accounts.

## Secrets

Never commit `.env`. On the VM, `FPL_SYNC_TOKEN` must be set or `POST /v1/sync` returns 503.
