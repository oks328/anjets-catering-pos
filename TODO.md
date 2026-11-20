# Remaining work

## Before production use

- Verify the full buffet and GCash workflows in a browser, including rejected proof and recovery.
- Configure and verify real Google sign-in and email delivery.
- Replace email threads with a durable queue, retry policy, and delivery tracking.
- Back up and restore the database and private uploads together; rehearse deployment migrations.
- Review sensitive files in existing Git history before public distribution. Current source deletions do not erase history.
- Verify migrations and concurrency on the chosen production database engine.
- Confirm the business's tax/discount allocation and receipt requirements.

## Follow-up improvements

- Add event capacity, unavailable dates, operating hours, and delivery zones.
- Move large carts out of cookie sessions; add pagination and measure query performance.
- Audit remaining dialogs, forms, and tables for keyboard access and small screens.
- Decide retention and cleanup rules for replaced images and abandoned payment proof.
- Integrate a real payment provider before enabling cards.
