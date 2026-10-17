# Private E-commerce deployment

E-commerce customer data must not be committed or published through GitHub Pages. The other static dashboard pages remain available on Pages; E-commerce requires the Docker backend.

## Coolify configuration

- Set a strong `ECOM_PASSWORD` as a Coolify secret. If omitted, the existing `BASIC_AUTH_PASSWORD` is reused. With neither configured, the E-commerce API denies access rather than serving public data.
- Mount a persistent private volume at `/var/lib/ops-private`. `ECOM_OUT` defaults to `/var/lib/ops-private/ecom.json` in Docker. Keep this path outside the nginx document root.
- Before the first deployment of this migration, transfer the last verified complete snapshot to that private volume as `ecom.json`. Do not upload it to the public repository, PR, Pages, or public build artifacts. The local CLI defaults to `private/ecom.json`, which Git and Docker ignore.
- Use HTTPS. Session cookies are Secure, HttpOnly, SameSite=Strict, expire after eight hours, and are revoked by Lock. `ECOM_COOKIE_SECURE=0` is only for local HTTP development.
- The entrypoint starts the loopback-only authorization service and refreshes the private snapshot from the existing Drive source. nginx proxies both the snapshot request and session endpoints to that service. The UI contains no password.

The refresh retains the last complete snapshot if any workbook cannot be read, a reporting month/sub-order/complaint disappears, or the source date moves backwards. It does not cache a failed build. An intentional correction that removes history requires an operator to review it and explicitly set `ECOM_ALLOW_REGRESSION=1` for that run; do not leave it enabled.

## Existing public exposure

Removing the snapshot from the latest branch does not remove previously published copies or Git history. Restrict repository visibility and source-workbook sharing, remove old Pages artifacts/deployments containing customer data, and follow the organisation's data-exposure process. Restricting repository visibility affects the other Pages-hosted dashboards, so coordinate that change with the dashboard owner. Do not rewrite shared Git history without an agreed recovery plan.

## Verification after deployment

Check that unauthenticated snapshot requests return 401, valid login allows access, Lock revokes that session, and server responses are not cached. Confirm the expected source date/months, customer drilldown, and completed-order delivery-date metrics in the private dashboard. A successful GitHub merge or Pages deployment does not prove Coolify is running this release.
