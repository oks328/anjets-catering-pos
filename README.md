# Anjet's Catering

Flask application for advance catering orders, buffet packages, and administrative order management.

## Run locally on Windows

Use Python 3.11 or newer. From the project folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Set a unique `SECRET_KEY` in `.env`. Generate one with:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

For local testing, use `APP_ENV=development`, `DATABASE_URL=sqlite:///site.db`,
`SESSION_COOKIE_SECURE=0`, and `MAIL_SUPPRESS_SEND=1`. Then run:

```powershell
.\.venv\Scripts\python.exe -m flask --app run db upgrade
.\.venv\Scripts\python.exe -m flask --app run create-admin --username dev-admin
.\.venv\Scripts\python.exe -m flask --app run seed-demo
.\.venv\Scripts\python.exe -m flask --app run run --host 127.0.0.1 --port 5001
```

Open [the customer site](http://127.0.0.1:5001/) and
[admin login](http://127.0.0.1:5001/admin/login) in separate browser profiles or an incognito window.
Keep PowerShell open; Ctrl+C stops the server. `python run.py` uses port 5000 instead.

The admin command prompts for a hidden, confirmed password and refuses to replace an existing user.
Demo seeding adds two trays without overwriting existing products and only runs against development
SQLite databases. On an already configured machine, start from `db upgrade`; keep the existing `.env`,
database, and accounts. Generated development credentials are in ignored `.local/` files.

## Test the workflow

1. Register a customer or use the local test account.
2. Add menu items or build a buffet. Standard orders require three days of lead time; buffet orders require seven.
3. Choose pickup or delivery and cash or GCash. Delivery currently adds a flat ₱100 fee.
4. For local GCash testing, use a sample image and dummy 13–14 digit reference; no real payment is needed.
5. In admin, review GCash proof when applicable, approve the order, and advance the available status.
6. Complete the order, check the customer's receipt, and review sales reports.

Pickup proceeds from Approved → In Progress → Completed. Delivery adds Up for Delivery before
completion. Completing a cash order confirms collection of the full payment. Declining an approval
request requires a reason. Only completed, paid orders count toward sales, grouped by completion day
in `BUSINESS_TIMEZONE` (default `Asia/Manila`). Unpaid approved orders have printable summaries.

Card payments are disabled until a real provider is integrated. Local email is suppressed, and
live Google sign-in requires separate configuration.

## Configuration

See [.env.example](.env.example) for available settings. Google sign-in uses
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `GOOGLE_OAUTH_REDIRECT_URI`.
Register the exact callback, such as `http://127.0.0.1:5001/auth/google/callback`, with Google.
For local HTTP OAuth only, explicitly set `OAUTHLIB_INSECURE_TRANSPORT=1`; production callbacks use HTTPS.
The flow checks state, PKCE, and verified email before linking accounts.

For real email, configure `MAIL_USERNAME` and `MAIL_PASSWORD`, then set `MAIL_SUPPRESS_SEND=0`.
Notifications currently use background threads: they are best effort, without a durable retry queue.
`verify_config.py` reports whether credentials are configured without printing their values.

For deployment, supply a persistent secret, configure the target database, run migrations, use a
production WSGI server behind HTTPS, and set `SESSION_COOKIE_SECURE=1`. Debug mode is off by default.
Forwarded IP headers are not trusted automatically; configure trusted proxy handling before relying
on per-client IP limits behind a proxy. This repository does not include a production deployment pipeline.

## Data and migrations

The default SQLite database is `instance/site.db`; uploads requiring authorization live in
`private_uploads/`. Both are ignored by Git and must be backed up together. Admin download routes
serve IDs and payment proof; public static URLs reject private upload folders and Windows path aliases.
A reverse proxy must also avoid serving private directories directly.

**Existing installations: preserve uploads before pulling this update.** Copy the contents of
`app/static/uploads/ids/`, `payments/`, and `riders/documents/` into the matching paths beneath
`private_uploads/` before source deletions are applied. These local files are not distributed by Git.
The admin download route retains a protected legacy fallback during migration. This machine's 73
legacy files were moved locally; files from earlier commits still require a separate history/privacy
review before making the repository public. No history rewrite is included.

Apply updates with `python -m flask --app run db upgrade`. Do not delete a database to change its schema.
For a model change, generate and review a migration before applying it:

```powershell
.\.venv\Scripts\python.exe -m flask --app run db migrate -m "Describe the change"
.\.venv\Scripts\python.exe -m flask --app run db upgrade
```

Migrations stop on duplicate normalized emails or invalid legacy menu values instead of merging or
deleting records. Older completion timestamps are approximated from order dates. Historical item
names are backfilled from the menu available at migration time; earlier names cannot be reconstructed.

## Pricing, checkout, and imports

Amounts use decimal arithmetic. Discounts round to cents before VAT, using `ROUND_HALF_UP`; the
final total adds those rounded components. The existing 12% VAT rate and highest-unit verified-discount
allocation are preserved. Valid prices are positive, have no fractional cents, and fit `Numeric(10, 2)`.
Oversized carts remain editable but cannot proceed to checkout.

The review uses current menu prices. A changed quote requires reconfirmation, and changed GCash
quotes invalidate prior proof. A unique server-issued checkout token prevents duplicate orders and
repeat voucher redemption under overlapping requests. Item descriptions are saved on each order;
renaming the menu does not change receipts, exports, or historical reports. Referenced sizes cannot be deleted.

CSV imports accept UTF-8, optional BOM/header, and exactly six columns:
`category, product name, description, has variants, price, size`. Every row needs a valid price and size.
Repeat a new product with `True` and a different size for multiple variants. Existing products are
skipped. Valid rows commit together; invalid rows are reported. Malformed files roll back in full.

## Authentication controls

Admin routes require the Admin role. Customer and administrator sessions become invalid after a
password change. Reset links stop working after a password change; older sessions must sign in again.

| Action | Account limit | Source IP limit |
| --- | --- | --- |
| Customer/admin login | 5 per 15 minutes | 30 per 15 minutes, per endpoint |
| Reset email request | 3 per hour | 10 per hour |
| Reset submission | — | 10 per hour |

Limits count attempts for known and unknown accounts, persist across workers, and use HMAC keys
rather than raw identities. Throttling returns HTTP 429 with `Retry-After`; unavailable counter storage
returns HTTP 503. Expired counters are cleaned up during authentication requests. Limits are in `Config`.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests config.py run.py recreate_db.py verify_config.py
.\.venv\Scripts\python.exe -m ruff format --check app tests config.py run.py recreate_db.py verify_config.py
.\.venv\Scripts\python.exe -m flask --app run db check
```

Tests use isolated databases. See [tests/README.md](tests/README.md), [DESIGN.md](DESIGN.md),
[CHANGELOG.md](CHANGELOG.md), and [TODO.md](TODO.md) for verification, UI conventions, release changes,
and remaining work.

Routes register explicitly for each app instance. Pricing, checkout validation, authentication,
rate limits, order transitions, reporting, CSV imports, and setup commands have separate modules.
