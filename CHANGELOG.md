# Changelog

## Unreleased

- Align the admin dashboard and shell with the client palette, typography, focus states, and responsive navigation.
- Add decimal cent rounding, server-side checkout validation, quote reconfirmation, and duplicate-order protection.
- Preserve historical item descriptions and prevent deleting sizes referenced by orders.
- Enforce order/payment transitions and report only completed, paid sales in Manila business-day boundaries.
- Add CSRF protection, private document downloads, Windows path-alias protection, role checks, rate limits,
  password-dependent sessions, and reset-token invalidation.
- Consolidate Google sign-in with verified email linking, one-use state, PKCE, and configurable callbacks.
- Add versioned database migrations, safe administrator creation, and repeatable development menu seeding.
- Validate CSV rows before persistence and support multiple sizes without partial invalid products.
- Register routes per application instance and consolidate duplicate decorators/imports and shared UI tokens.
- Remove obsolete card collection forms, integration snippets, stale activation notes, and empty root files.
- Move tracked private uploads into ignored local storage; preserve them before updating another installation.
- Add regression tests and Ruff checks. Real payment processing, durable email retries, and production deployment remain separate work.
