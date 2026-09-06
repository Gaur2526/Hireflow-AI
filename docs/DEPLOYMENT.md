# Deployment

Four ways to run this app, honestly compared. Pick one, follow the steps, done.

> **Read this first — the persistence trap.**
> The default `DATABASE_URL` is `sqlite:///./data/hireflow.db`. That file lives on
> the container's own filesystem. **Render's free plan has no persistent disk and
> Vercel's filesystem is ephemeral**, so on both of them the database is silently
> wiped on every deploy, restart, or wake-from-sleep. Fine for a five-minute demo;
> not fine for anything you want to still exist tomorrow. Point `DATABASE_URL` at
> [Neon](https://neon.tech) Postgres and the problem disappears.

---

## 1. Which option should I pick?

| | Free tier | Card required | Data persists | Cold start | Effort | Best for |
|---|---|---|---|---|---|---|
| **(a) Render backend + Vercel frontend** | Render: 750 instance-hrs/workspace/mo. Vercel Hobby: 100 GB bandwidth | **No** | Only with Neon (Render free has **no disk**) | ~1 min after ~15 min idle | ~15 min | **Recommended.** Real split deploy, both halves free |
| **(b) All-Vercel (frontend + FastAPI) + Neon** | Vercel Hobby | **No** | Yes, via Neon (Vercel FS is ephemeral) | ~1–3 s (serverless) | ~20 min | One dashboard, fastest cold start |
| **(c) `docker compose` locally** | Free | No | Yes, named volume | None (always on) | ~2 min | Running both halves locally with one command |
| **(d) Local + `cloudflared`** | Free, no account | **No** | Yes (your disk) | None | ~2 min | Testing Hunar **webhooks** against your laptop |

Other facts worth knowing before you commit:

- **Neon** free: 0.5 GB, scales to zero, and is **not** paused for inactivity. Best free Postgres.
- **Supabase** free: pauses a project after ~1 week of inactivity — you must un-pause it by hand.
- **Render Postgres** free: **expires 30 days after creation** and is then deleted. Scratch only.
- The **Render CLI cannot apply a Blueprint.** `render.yaml` has to be imported once in the
  dashboard; after that `scripts/deploy-render.sh` redeploys via the API.
- `brew install render` installs an **unrelated** package. Use the official installer
  (see below) if you want the CLI at all.
- On **Vercel**, background loops do not run between requests. Set
  `ENABLE_CALL_POLLER=false` and rely on webhooks, or call results only reconcile
  while a request happens to be in flight.

---

## 2. Environment variables, and where each one goes

Everything the backend reads is defined in `backend/app/core/config.py`. Full list with
defaults lives in `render.yaml`; this is the short version of what actually matters.

**Backend** (Render / Vercel / container env):

| Variable | Set it to | Secret |
|---|---|---|
| `HUNAR_API_KEY` | your Hunar key — without it no calls are placed | **yes** |
| `HUNAR_WEBHOOK_SECRET` | only if your org got a separate signing secret (otherwise Hunar signs with the API key) | **yes** |
| `DATABASE_URL` | `postgresql+psycopg://USER:PW@ep-xxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require` | **yes** |
| `PUBLIC_BASE_URL` | the backend's own public HTTPS URL, e.g. `https://hireflow-ai-api.onrender.com`. Empty ⇒ webhooks are skipped and the poller is used instead | no |
| `CORS_ORIGINS` | the frontend origin, e.g. `https://hireflow-ai.vercel.app` (comma-separated, or `*`) | no |
| `PEOPLE_PROVIDER` | `mock` \| `pdl` \| `apollo` \| `coresignal` | no |
| `PDL_API_KEY` / `APOLLO_API_KEY` / `CORESIGNAL_API_KEY` | vendor key for the chosen provider | **yes** |
| `ANTHROPIC_API_KEY` | optional; without it JD parsing falls back to a deterministic parser | **yes** |
| `DEMO_CALL_REDIRECT_NUMBER` | E.164 number that receives **every** outbound call. Set this for demos so no stranger is called | **yes-ish** |
| `ENABLE_CALL_POLLER` | `true` on Render/Docker, `false` on Vercel | no |
| `ENVIRONMENT` | `production` | no |

**Frontend** (Vercel project env, or `frontend/.env.local`):

| Variable | Set it to |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | the backend's public URL, e.g. `https://hireflow-ai-api.onrender.com`. Leave **empty** in the single-container build — the frontend is same-origin there. |

`NEXT_PUBLIC_*` values are **baked in at build time**. Change one ⇒ redeploy the frontend.

No secret belongs in a committed file. `.env` is git-ignored; `.env.example` is the template.

---

## 3. (a) Render backend + Vercel frontend — recommended

### Step 1 — Postgres on Neon (2 min, skip only for a throwaway demo)

1. https://neon.tech → sign up → **Create project**.
2. Copy the **pooled** connection string.
3. Rewrite the scheme for SQLAlchemy + psycopg 3 and keep TLS:
   ```
   postgresql+psycopg://USER:PASSWORD@ep-xxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require
   ```
   (Neon hands you `postgresql://…`; the `+psycopg` part is what selects the installed driver.)

### Step 2 — backend on Render

```bash
git push          # render.yaml must be on the branch you deploy
```

1. https://dashboard.render.com/select-repo?type=blueprint → pick this repo.
   Render reads `render.yaml` and creates a **Docker** web service that builds
   `backend/Dockerfile` with `backend/` as its context, health-checked at `/healthz`.
2. It prompts for every `sync: false` variable. Paste at minimum:
   `HUNAR_API_KEY`, `DATABASE_URL` (the Neon URL), `CORS_ORIGINS` (put
   `http://localhost:3000` for now), and leave `PUBLIC_BASE_URL` empty.
3. Apply. First build ≈ 3–5 min.
4. When it's live, note the URL — `https://<service-name>.onrender.com` — then set
   `PUBLIC_BASE_URL` to exactly that in **Environment** and redeploy. (Render only
   knows its own URL after the first deploy; that is why it isn't a literal in `render.yaml`.)
5. Verify:
   ```bash
   curl https://<service-name>.onrender.com/healthz     # {"status":"ok"}
   ```

Redeploy later, non-interactively:

```bash
export RENDER_API_KEY=rnd_xxx     # https://dashboard.render.com/settings#api-keys
./scripts/deploy-render.sh
```

Optional CLI (**not** `brew install render`):

```bash
curl -fsSL https://raw.githubusercontent.com/render-oss/cli/refs/heads/main/bin/install.sh | sh
```

### Step 3 — frontend on Vercel

```bash
export VERCEL_TOKEN=xxx           # https://vercel.com/account/tokens
npm i -g vercel
cd frontend && vercel link        # once, interactively
cd .. && ./scripts/deploy-vercel.sh frontend
```

Or via the dashboard: **New Project** → this repo → **Root Directory: `frontend`**
(Vercel auto-detects Next.js; `frontend/vercel.json` pins the install/build commands).

Then in the Vercel project → **Settings → Environment Variables**:

```
NEXT_PUBLIC_API_BASE_URL = https://<service-name>.onrender.com
```

Redeploy the frontend (build-time variable).

### Step 4 — close the CORS loop

Back on Render, set `CORS_ORIGINS` to your Vercel URL (e.g. `https://hireflow-ai.vercel.app`)
and redeploy. Open the site — it should load candidates without console CORS errors.

### Step 5 — webhooks

`PUBLIC_BASE_URL` is already the Render URL, so the app registers
`https://<service>.onrender.com/api/webhooks/hunar/*` with Hunar automatically.
**Caveat:** the free service sleeps after ~15 min idle, so the first webhook after a
quiet period waits ~1 min for the cold start. The background poller
(`ENABLE_CALL_POLLER=true`) reconciles anything that gets dropped.

---

## 4. (b) All-Vercel + Neon

Same Neon step as above, then two Vercel projects from the same repo.

**Backend project** — Root Directory `backend`. `backend/vercel.json` routes every path
into `app/main.py` via `@vercel/python`, so the ASGI app is served as a serverless function.

Environment variables:

```
DATABASE_URL        = postgresql+psycopg://…neon.tech/neondb?sslmode=require   # REQUIRED - no SQLite here
HUNAR_API_KEY       = …
PUBLIC_BASE_URL     = https://<backend-project>.vercel.app
CORS_ORIGINS        = https://<frontend-project>.vercel.app
ENABLE_CALL_POLLER  = false      # serverless functions have no background loop
ENVIRONMENT         = production
```

```bash
VERCEL_TOKEN=xxx ./scripts/deploy-vercel.sh backend
curl https://<backend-project>.vercel.app/healthz
```

**Frontend project** — Root Directory `frontend`, `NEXT_PUBLIC_API_BASE_URL` pointing at
the backend project's URL, then `./scripts/deploy-vercel.sh frontend`.

Honest trade-offs versus (a):

- Cold starts are seconds, not a minute, and there is no 15-minute sleep. Nicer demos.
- **SQLite cannot be used at all.** Neon (or any managed Postgres) is mandatory.
- No background poller ⇒ call status depends entirely on Hunar's webhooks reaching you.
- Long-running requests are capped by the function timeout (60 s on Hobby); the app's
  request handlers are short, but keep it in mind.

---

## 5. (c) Why there is no single-image option

One container serving both halves would be neat — one URL, no CORS. It is not
possible here without changing the app, so this repo does not ship a broken
Dockerfile pretending otherwise.

Serving the frontend from FastAPI needs a static export (`output: "export"`).
Next.js refuses to export a dynamic route segment unless the page provides
`generateStaticParams()`, and `/campaigns/[id]` and `/jobs/[id]` resolve their id
in the browser — there is no fixed set of paths to prerender. Working around it
means prerendering under a placeholder id and reading the real one back out of
`window.location`: a workaround living permanently in production code to serve a
deployment shape nobody has to use.

What to do instead:

- **Locally, one command** — `docker compose up --build` runs the backend image
  and the frontend dev server side by side, CORS already configured.
- **Deployed** — option (a) or (b) above. Both are free, and both work today.
- **`backend/Dockerfile` is complete and working** on its own; it is what Render,
  Fly.io, Railway and Koyeb all consume.

```bash
docker compose up --build             # backend :8000 + frontend :3000
docker compose --profile postgres up  # ...plus Postgres on :5432
docker compose down -v                # stop and drop volumes
```

---

## 6. (d) Local + cloudflared, for webhook testing

Hunar has to reach you over public HTTPS. A Cloudflare **quick tunnel** gives you a URL
with no account and no config.

```bash
brew install cloudflared     # macOS; Linux: cloudflare.com docs
make dev                     # terminal 1: backend :8000 + frontend :3000
make tunnel                  # terminal 2
```

`scripts/tunnel.sh` starts `cloudflared tunnel --url http://localhost:8000`, extracts the
generated `https://<random>.trycloudflare.com` URL, and writes it into `backend/.env` as
`PUBLIC_BASE_URL` — replacing any existing line instead of appending a duplicate.

Then **restart the backend**: `uvicorn --reload` watches source files, not `.env`, so a
new `PUBLIC_BASE_URL` is only picked up on a fresh start. Ctrl-C `make dev` and rerun it.

Check it end to end:

```bash
curl https://<random>.trycloudflare.com/healthz      # {"status":"ok"}
```

Hunar will call `https://<random>.trycloudflare.com/api/webhooks/hunar/{status,recording,result,summary}`.

Caveats: the URL changes on every run (rerun `make tunnel`, restart the backend), and it
dies when you close that terminal. Set `DEMO_CALL_REDIRECT_NUMBER` while testing so every
call lands on your own phone.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Data vanished after a deploy | SQLite on an ephemeral filesystem | Set `DATABASE_URL` to Neon |
| `sqlalchemy.exc.NoSuchModuleError: postgresql.psycopg` | URL starts with `postgresql://` | Use `postgresql+psycopg://` |
| Browser console: CORS blocked | `CORS_ORIGINS` doesn't include the frontend origin | Add the exact scheme+host, redeploy the backend |
| Frontend calls `localhost:8000` in production | `NEXT_PUBLIC_API_BASE_URL` wasn't set **before** the build | Set it in Vercel, redeploy |
| First request takes ~60 s | Render free spin-down after ~15 min idle | Expected; upgrade or accept it |
| Webhooks never arrive | `PUBLIC_BASE_URL` empty or not `https://` | Set it; the app falls back to polling meanwhile |
| Call results stale on Vercel | No background poller on serverless | Rely on webhooks; keep `ENABLE_CALL_POLLER=false` |
| `render` command does something unrelated | `brew install render` is the wrong package | Use the official `install.sh` above |
