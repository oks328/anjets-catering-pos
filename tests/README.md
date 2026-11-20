# Regression tests

Install `requirements-dev.txt`, then run `python -m pytest -q`.
Tests use a temporary, in-memory SQLite database; they do not touch your configured database.

## Strategy

Criticality: high (authorization, checkout, data integrity).

| Gate | Decision | Reason |
| --- | --- | --- |
| Skip all | Off | Changes affect security and stored orders. |
| Unit | On | Input validation and date/quantity boundaries. |
| Integration | On | Real Flask requests, SQLAlchemy transactions, and rendered templates. |
| Component/E2E | On, deferred | Browser checkout verification needs a configured application; request/template tests cover this batch. |
| Contract | Off | Templates and server deploy together. |
| Smoke | Off | No deployment pipeline exists yet. |
| Property-based | On | Generated prices and fractional discounts are checked against an independent integer-cent oracle. |

Selected tests: pytest integration tests (medium size, local SQLite and temporary filesystem),
with parameterized validation cases in the same request-level tests. Mocking the ORM would hide
the transaction bug, so tests exercise actual database writes and an injected insertion failure.

Cases cover quantities -1/0/1, missing/malformed dates and times, standard/buffet lead times,
unsupported payment methods, stale prices, inactive categories, invalid vouchers, rollback,
CSRF rejection, safe flash rendering, private uploads, and removal of the destructive endpoint.

Deliberately skipped: external OAuth/email/payment calls, production database engines, visual
regression, and exhaustive monetary input coverage. These need separate fixtures and changes.

The second batch adds order-state transition cases, stale payment-verification actions,
notification-queue failures, completed/paid sales filtering, business-day boundaries,
SQLite template rendering, legacy-data migrations, account normalization, reset-token
invalidation, admin role checks, and Google account linking. Google SDK/HTTP boundaries are
stubbed; actual OAuth consent and email delivery still require configured integration testing.

The third batch covers decimal cent rounding, price/quantity boundaries, 200 deterministically
generated monetary cases (pytest plus standard-library random), historical descriptions,
CSV row validation and multiple sizes, database constraints, legacy backfills, and correction
of oversized carts. Pricing tests preserve the existing discount allocation policy; they do
not establish new tax rules.

The fourth batch tests retries and stale tabs, two genuinely overlapping file-backed SQLite
checkouts, voucher redemption under contention, password-based session revocation, persistent
login/reset limits, expiry boundaries, IP limits across account names, and safe setup commands.
Concurrency is exercised in a separate process so connections do not share the in-memory fixture.

The frontend cleanup adds factory reinitialization coverage and regressions for Windows static-path aliases, current checkout quotes, and GCash proof invalidation when totals change. Desktop and mobile dashboard checks use an isolated preview database; external OAuth and email delivery remain integration checks.
