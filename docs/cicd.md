# CI / CD

This document is the contract for GitHub Actions. Local Docker and the Oracle VM still live in [deploy.md](deploy.md). Image **publish** and **VM apply** are not fully wired yet; tag rules and security gates below are what we will implement against.

Package (lowercase, required by GHCR): `ghcr.io/zchaarim/fpl-radar-backend`

Version in tags comes from `pyproject.toml` (today `0.1.0`). Channel is `rel` (production-capable, from `main`) or `dev` (PR preview). Commit is the short SHA.

```text
ghcr.io/zchaarim/fpl-radar-backend:0.1.0-rel-a1b2c3d
ghcr.io/zchaarim/fpl-radar-backend:rel
```

Moving pointers `:rel` and `:dev` always refer to the latest successful publish on that channel. Prefer the immutable `version-channel-sha` tag when you actually deploy.

## CI (test and build)

Workflow: `.github/workflows/ci.yml`. Also CodeQL (`.github/workflows/codeql.yml`) and Dependabot (`.github/dependabot.yml`).

| Event | pytest, Gitleaks, pip-audit, Bandit, Ruff, Hadolint, Trivy fs + image | `docker build` | Push to GHCR |
|---|---|---|---|
| **PR into `main` / `master`** | Yes | Yes | **No**, unless `PUSH_DEV_IMAGE_ON_PR` is `true` on that workflow run |
| **PR + `PUSH_DEV_IMAGE_ON_PR=true`** (same-repo only) | Yes | Yes | **Yes**, channel **`dev`** only (`0.1.0-dev-<sha>` and `:dev`) |
| **Push / merge to `main` / `master`** | Yes | Yes | **Yes**, channel **`rel`** (`0.1.0-rel-<sha>` and `:rel`) |
| **Fork PR** | Yes (tests/scans/build) | Yes | **Never** |

`PUSH_DEV_IMAGE_ON_PR` is a boolean in `ci.yml` (`env`). GitHub runs the workflow file from the **PR branch**, so setting it `true` on that branch opts **that** PR into a `dev` publish. Leave it `false` on `main` so ordinary PRs stay build-only.

### No push on fork PRs

Forks must not receive `packages: write`. Even if someone sets `PUSH_DEV_IMAGE_ON_PR: true` on a fork, CI must skip GHCR when:

`github.event.pull_request.head.repo.full_name != github.repository`

Otherwise an outsider could push images into our package namespace or steal a write token. GitHub-hosted `GITHUB_TOKEN` for `pull_request` from a fork is already read-limited; we still encode the check in YAML so we never add a push step that assumes the head repo is us.

Do not use `pull_request_target` to “fix” fork builds. That checkout model can run untrusted code with base-repo secrets.

GHCR publish (when it is added) needs `permissions: packages: write` **only** on the job that pushes, and only after the fork check.

## CD (apply an image to a VM)

Manual: GitHub Actions **`workflow_dispatch`** (Actions tab → Run workflow, or `gh workflow run`). Inputs:

- **image tag** (immutable tag preferred, or `:rel` / `:dev`)
- **development** and/or **production** (booleans; GitHub has no real multi-select)

`.github/workflows/deploy.yml` **refuses production** unless the tag is on the **`rel` channel** (`rel` pointer or `*-rel-*`). A **`dev`** tag (or any non-`rel` channel) cannot go to production. That guard is in YAML today; pulling the image onto Oracle is **not** implemented yet.

GitHub **Environments** (`development`, `production`) should hold per-env secrets later (required reviewers on production are optional).

### How CD might reach the Oracle VM (undecided)

Two options; **do not pick one in code yet**.

**1. GitHub-hosted runner + SSH**  
The job SSHs from GitHub’s cloud into the Always Free VM and runs `docker pull` / `compose up`.

- Pros: no extra process on the VM; runners are patched by GitHub; easy to disable.
- Cons: the VM must accept SSH from a large, changing GitHub IP range (or a tunnel). That is a wide hole if you open port 22 to the world. Secrets (SSH key) live in GitHub; a stolen key is inbound access to the box.

**2. Self-hosted runner on the Oracle VM**  
The CD workflow is **allowed** to use a runner labeled for that VM. The job is already on the machine: `docker pull` from GHCR, compose up. No inbound SSH for deploys.

- Pros: no public SSH for CD; lowest friction with Always Free “always on”; matches a warm API process.
- Cons: you operate the runner (updates, disk). **Never** attach that runner to `pull_request` jobs — a fork PR would execute on your VM. Use it only for `workflow_dispatch` / `push` to `main`. If the VM is compromised, the runner’s token is too.

Either way: `.env` stays on the VM; GHCR credentials if the package is private; never commit tokens.

## What CI does not do

- Host the API 24/7.
- Deploy on merge (that will be a later job on **push to `main`**, or stay manual-only).
- Trust workflow flags from forks.
