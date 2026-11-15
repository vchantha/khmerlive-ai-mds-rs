# KhmerLive AI User Accounts & Social Login (research MVP)

The redesigned dashboard has a collapsible desktop sidebar, a mobile drawer and a **Users & Social** page.

## Supported OAuth identities

- **Google**: OpenID Connect (name, verified profile, email when provided).
- **Facebook**: OAuth 2.0 / Graph API (name, email only if provided).
- **GitHub**: OAuth 2.0 (name, handle, public email when available).
- All three are **disabled until configured**; do not expect a social sign-in button to work without provider credentials and valid callback domains.
- Sign-in creates an `app_users` record and a `social_identities` record in PostgreSQL. When signed in, choose **Link account** for another provider. A provider identity already owned by a different user cannot be linked. Linking by matching email alone is not allowed.
- Social access tokens are not persisted in PostgreSQL. A signed, HttpOnly, SameSite=Lax session cookie is used for browser login.
- Social users can see and act on **only jobs they own**. Admin API-key access remains for trusted local testing; **do not expose it to untrusted users**.

## 1. Configure private environment

Your existing `.env` is **not replaced** on `git pull`. Generate a strong random signing key:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

In your private `.env` (never push it), configure:

```env
AUTH_SESSION_SECRET=<your-generated-long-secret>
AUTH_PUBLIC_BASE_URL=https://khmerlive.yourdomain.example
AUTH_COOKIE_SECURE=true
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
FACEBOOK_CLIENT_ID=
FACEBOOK_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

Replace the example domain and credentials. For **localhost-only testing**, use `AUTH_PUBLIC_BASE_URL=http://localhost:8080` and `AUTH_COOKIE_SECURE=false`. **Use HTTPS and secure cookies on externally reachable systems**. The Nginx gateway must pass the externally visible Host and scheme; place a TLS terminator/reverse proxy in front of port 8080 in production.

## 2. Register provider callback URLs

Create the OAuth application in each provider's developer console; add the exact externally reachable callback URI:

| Provider | Callback URL |
| --- | --- |
| Google | `https://khmerlive.yourdomain.example/api/auth/callback/google` |
| Facebook | `https://khmerlive.yourdomain.example/api/auth/callback/facebook` |
| GitHub | `https://khmerlive.yourdomain.example/api/auth/callback/github` |

Google uses OIDC configuration, Facebook uses its Graph API, and GitHub uses its OAuth App authorization flow. Review each provider's app-verification, privacy policy and testing-user requirements. Avoid using a personal access token as an OAuth Client Secret. Any provider-specific permitted redirect restrictions must be satisfied.

## 3. Redeploy, smoke-test and link accounts

```bash
git pull origin main
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
docker compose run --rm --no-deps api pytest -q
curl -s http://localhost:8080/api/auth/providers
curl -s http://localhost:8080/api/auth/me
```

Open the dashboard. Click **Users & Social**, select a configured sign-in provider, complete its real OAuth consent flow, then connect another provider with **Link account**. Confirm a linked provider appears in the database-backed list. Signing out clears the browser login session. An existing API key can still be used for local administrator tasks.

If providers are disabled in the UI, check names `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FACEBOOK_CLIENT_ID`, `FACEBOOK_CLIENT_SECRET`, `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` **without printing their values**. Social OAuth is not fully verifiable without real client credentials, internet access to the provider and a browser login.

## Database & migration

Alembic revision `0006_user_social_auth` creates user identities and nullable ownership fields. Existing demo jobs have no user owner and remain accessible via the privileged API key; they will not be exposed to newly signed-in social users. Never run `docker compose down -v` on an existing data volume.

## Security limitations

This is **research MVP authentication**, not a fully audited identity platform. Before public launch: remove the shared admin API key from the browser UX, rotate credentials, use HTTPS only, add CSRF protection to cookie-authenticated mutations, set an allowlist for sign-ups, implement organization roles and SSO, account deletion, user audit logs, session revocation, rate limits, security event monitoring, and test OAuth thoroughly. If an administrator uses a cached API key while signed in, the account session takes precedence to preserve per-user isolation. Browser sessions are not an enterprise session-management system.
