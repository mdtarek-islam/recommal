# Deployment

This guide deploys the Streamlit app. The model pipeline does not run in production.
The app reads precomputed rows from Supabase PostgreSQL.

Platform limits and prices change. Check each linked page before you commit to a plan. The author did not fetch these pages when writing this file.

## 1. Why not Vercel

Streamlit holds one WebSocket per browser session for the whole visit. Vercel Functions are short-lived.
The WebSocket support on Vercel Functions is in beta and has session caps of 5 to 30 minutes, so it does not suit Streamlit.
Source: [Ably, WebSockets on Vercel](https://ably.com/vercel/websockets-on-vercel).

Vercel stays useful for DNS. Section 4 uses it for the custom subdomain.

## 2. Recommended free path: Docker on Render

The repository holds the three files that Render needs: `Dockerfile`, `.dockerignore` and `render.yaml`.
The image installs `requirements.txt` only. It holds no PyTorch and no model files.

| Property | Value to expect on the free plan | Check |
|---|---|---|
| Idle behaviour | The service sleeps after about 15 minutes without traffic | [Render free docs](https://render.com/docs/free) |
| Memory | 512 MB | [Render pricing](https://render.com/pricing) |
| Custom domains | Supported, with managed TLS | [Render custom domains](https://render.com/docs/custom-domains) |
| Bandwidth | Limits changed in 2026. Read the current limit | [Render pricing](https://render.com/pricing) |

### Steps

1. Apply the migrations to Supabase from your machine. Set the `DB_*` variables first.

   ```
   python -m db.migrate_and_seed
   ```

2. Push the repository to GitHub.
3. In the Render dashboard, choose New, then Blueprint. Select the repository. Render reads `render.yaml`.
4. Set each variable that `render.yaml` marks `sync: false`. Do not commit values.

   | Variable | Where to set it | Value source |
   |---|---|---|
   | `DB_HOST` | Render dashboard, Environment | Supabase session pooler host |
   | `DB_PORT` | Render dashboard, Environment | Supabase session pooler port |
   | `DB_NAME` | Render dashboard, Environment | Supabase connection string |
   | `DB_USER` | Render dashboard, Environment | Supabase connection string |
   | `DB_PASSWORD` | Render dashboard, Environment | Supabase database password |
   | `RECOMMAL_AB_SALT` | Render dashboard, Environment | Generated below |

5. Wait for the first build. Render uses the health path `/_stcore/health` from `render.yaml`.

### Supabase connection string

Use the **session pooler** string from Supabase: Project Settings, Database, Connection string.
The app keeps its own `ThreadedConnectionPool`, so a session connection fits. Check the Supabase docs on IPv4 and IPv6 access if the direct host fails from Render.

### Generate `RECOMMAL_AB_SALT`

The command runs on Windows and on a POSIX shell.

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output into the Render dashboard. Do not store it in git or in this file.
Keep the same value after launch. A new value changes every user pseudonym and bucket.

## 3. Idle-sleep trade-off

The free service sleeps when idle. The first request after a sleep waits for a cold start of the container.
The Streamlit session state resets on a restart, so users log in again.
A paid plan removes the sleep. A ping service can keep the service awake, but check the Render terms before you use one.

## 4. Custom subdomain with Vercel DNS

Use this route when the domain uses Vercel nameservers.

1. In Render, open the service. Open Settings, then Custom Domains. Add `app.example.com`.
2. Copy the target that Render shows in the Custom Domains panel.
3. Add a CNAME record. The name is the subdomain only (`app`). The value is the Render target.
   - Dashboard: Vercel, Domains, your domain, DNS Records.
   - CLI: `vercel dns add example.com app CNAME <target>`
4. Do not add an A record and a CNAME record for the same name.
5. In Render, choose Verify. Wait for the TLS certificate to issue. This can take several minutes.

Replace `example.com` and `<target>` with your values. Source: [Vercel, managing DNS records](https://vercel.com/docs/domains/managing-dns-records).

## 5. Post-deploy checklist

- [ ] Open `https://<your-host>/_stcore/health`. The page returns `ok`.
- [ ] Open the app. Register a test user. Log in. Search a title. Open a result.
- [ ] Confirm that a row appears in `ab_test_events` for the exposure event.
- [ ] Open the Render logs. Confirm that no warning says `RECOMMAL_AB_SALT is not set`.
- [ ] In Supabase, open Advisors. Fix every security finding for the `public` schema, especially tables without RLS.
- [ ] Confirm that the anon key cannot read `users`, `ab_test_events` or `login_attempts`.
- [ ] Delete the test user.

## 6. Alternatives

| Option | Cost | Custom domain | Note |
|---|---|---|---|
| [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud) | Free | No. You get a `streamlit.app` subdomain | Set the variables in the app Secrets panel |
| [Hugging Face Spaces (Docker)](https://huggingface.co/docs/hub/spaces-sdks-docker) | Free tier | Check current rules | The Space must listen on its configured port |
| [Google Cloud Run](https://cloud.google.com/run/pricing) | Check the current free allowance | Yes | Supports WebSockets. Set a request timeout |
| [Fly.io](https://fly.io/docs/about/pricing/) | Check the current free allowance | Yes | Use the same Dockerfile |

For every host, set the same six variables. The Dockerfile reads the port from `$PORT`.

## Sources

- Render: [pricing](https://render.com/pricing), [free plan](https://render.com/docs/free), [custom domains](https://render.com/docs/custom-domains).
- Vercel: [managing DNS records](https://vercel.com/docs/domains/managing-dns-records).
- Vercel WebSocket limits: [Ably](https://ably.com/vercel/websockets-on-vercel).
