# UI conventions

The client storefront is the visual authority for the admin workspace. This is an operational UI:
orders, payment checks, and event details must be easy to scan.

## Shared foundation

`app/static/css/brand.css` owns the shared palette, font loading, focus treatment, selection color,
and reduced-motion override. Both base templates load it before their surface stylesheet.

- Body: Inter; headings and wordmark: Poppins.
- Brand accent: `#e84c3d`; stronger action/text red: `#c0392b`.
- Background: `#f3f4f6`; panels: white; primary text: `#1f2937`.
- Muted text: `#6b7280`; borders: `#e5e7eb`; light accent surface: `#fff5f5`.
- Panel corners: 14px; ordinary controls: 8–10px. Focus rings stay visible.

Admin solid primary buttons use the stronger red for white-text contrast. Status colors communicate
state and are not decorative substitutes for the brand palette. Tabular data uses tabular numerals.

## Admin layout

A fixed sidebar supports desktop operations. Below 880px it becomes a collapsible navigation section
with a keyboard-operable Menu button, `aria-expanded`, and Escape-to-close behavior. Navigation
remains visible if JavaScript is unavailable.

Dashboard metrics form one divided panel; the pending-request table has its own labeled panel.
Below 1200px metrics use two columns. Wide tables scroll inside their labeled, focusable region
rather than widening the page. Empty states include a route back to the relevant task.

Preserve metric definitions and order/payment rules when changing presentation. Keep dashboard
styles scoped to `.dashboard-*`; shared admin controls use the existing `.btn`, `.card`, and form classes.
Chart.js loads only on the sales-report page.
