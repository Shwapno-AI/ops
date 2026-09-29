# Operations Dashboard

Sales achievement and growth visibility for Shwapno operations, fed automatically from one mother Google Drive folder.

## How the data gets in

GitHub reads the public mother Drive folder every hour (8 am to 11 pm Dhaka time), recognises each file by its content, and saves `data/data.json` (plus the network, consumable and availability files below). The site only reads those files. No API key is used. Downloads are cached between runs by Drive file and last-modified time, so only new or changed files are downloaded.

| Kind of file | What goes in it | Rule |
|---|---|---|
| Till-date | Daily till-date Business Performance Report | Replace the file each day |
| Month-end | Last month's closed Business Performance Report | Replace the file each month |
| Performance | KPI RHO & Zonal file, Zone Distribution and Outlet-wise Profitability (P&L) | Add new files each month, keep old ones |

Filenames and sub-folders don't matter: every file anywhere under the mother folder is recognised by its columns. The folder must stay shared as "Anyone with the link". A sub-folder whose name contains "Daily" or "Till" is preferred for the till-date report when two reports compete.

If a file is broken or missing, the refresh is rejected and the site keeps the last good data. The Data quality page lists every problem found.

### The mother Drive folder

All data now lives under one mother folder, [Operations data](https://drive.google.com/drive/folders/1Te9stxbcBsIIO8bNElPuDXXPovkk4v1l), shared as "Anyone with the link". The Outlet network, Growth & momentum and Consumable & wastage refreshes search every sub-folder of it and recognise each file by its columns, never by its name. The main sales pages read it the same way.

One till-date sales file (columns **Outlet, Date, Article Division, POS NSI**) feeds both the Outlet network pages and Consumable & wastage; keep it current. If two files of the same kind exist, the one whose data runs latest wins (for Zone Distribution, the most recently modified).

### Availability

The Availability pages read `data/av.json`, built by `scripts/av/refresh.py` from the mother folder. Files are recognised by their columns: the SKU lists (sheets with Article Code, Name, CAT3 and a CORE / PROMO / KVI / ECOM flag), the stock matrix (ProductCode, ProductName, one column per outlet; CSV or Excel), 60-day sales (Outlet Code, Article Code, Sales Qty, PER DAY), the E-Commerce file (Code, code, Monthly Average Sales (ECOM), DOS 2 Days, Assortment for outlet), the KVI outlet list (one CODE column) and Zone Distribution. Stock and sales should be uploaded daily; the pages warn when either is more than 2 days old.

Rules: an outlet with no Core, KVI or Promo stock, or no Core, KVI or Promo sales, is left out everywhere. A pair is available when stock covers the chosen days of sales (60-day sales ÷ 60 × days, default 2); a pair with no sales in 60 days counts and is available when it has stock. E-Commerce counts only Assortment = YES pairs and is available when stock covers DOS 2 Days. The KVI outlet list is only a filter on the KVI page.

### Store assessment

The Store assessment pages (Overview, Scorecard, Questions, Coverage and auditors) read `data/sa.json` and, when an outlet is opened, `data/sa-remarks.json`, both built by `scripts/sa/refresh.py` from the Store Operations Compliance Audit exports in the [Store Assessment folder](https://drive.google.com/drive/folders/1TJ_c7VVyg6Qa_o0c62_LsZkd0sBHDEHF) (set `SA_FOLDER_ID` to use another). Put one export per month there (the current month till date); files are recognised by their columns (Response Summary and Answer Details) and each month comes from the audit dates, so replacing a file replaces its month. Each audit scores one outlet on 41 questions in 6 categories (290 points); an outlet's score for a month is its latest audit that month, and grades are Excellent 85%+, Good 75–84%, Needs work 65–74% and Critical below 65%. A workbook that has not changed in Drive is not downloaded again: its audits are reused from the previous `sa.json`.

### Receiving

The Receiving pages read `data/rcv.json`, built by `scripts/rcv/refresh.py`. The figures come from the public Power BI receiving report; the Receiving dashboard's own workflow reads that report every few minutes and publishes `snapshot.json`, which this step downloads (set `RCV_SNAPSHOT_URL` to read a different snapshot). On the Docker/Coolify server it runs every 10 minutes (`RCV_MINUTES`), followed by `scripts/rcv/drill.mjs` (Node), which asks Power BI for the drill-down levels of the default view (business division, category, article, and article × outlet) one category at a time and writes `data/rcv-drill/` (not committed). The pages read those files instead of waiting for Power BI; anything the snapshot doesn't cover, and every other filter, is read live and kept for 10 minutes. Outlets are joined to the outlet master for the sidebar filters. Over-receiving value is a non-additive Power BI measure, so it is shown for the company, a division, a category or one outlet, never summed.

### Item performance

The Item performance pages read `data/sku.json` (and `data/sku-rl.json` for one regional leader's SKUs), built by `scripts/sku/refresh.py` from the **Item Dashboard performance workbooks** Drive folder (set `SKU_FOLDER_ID` to use another folder). Each workbook holds one row per outlet and SKU with this-year and last-year POS sales (NSI), GP value and quantity; files are recognised by their columns, which may be named "POS NSI This" or "Sales This" and so on. The workbooks are large, so the build streams them and publishes summaries (outlet totals, outlet x division x Cat 01, SKU totals, SKU x regional leader and each outlet's biggest gaining and declining SKUs). It only rebuilds when a workbook changed. Same store uses the Business Performance Report's same-store list. Footfall and basket size are left out because in these files they are per SKU line and don't add up.

### Outlet network and Growth & momentum

These two pages are built into this dashboard and read `data/network.json`, which the same hourly refresh builds from the mother folder. It needs these workbooks, anywhere under it:

| Workbook | How it is recognised | Required |
|---|---|---|
| Outlet master / Zone Distribution | `CODE` + `Outlet Name` header with `Leader` / `Zonal` / `Format` columns | yes |
| Day-wise target | `Outlet Code` + `Outlet Name` header followed by daily date columns | yes |
| Day-wise sales | the till-date sales file: `Outlet` (or `Outlet Code`) + `Date` + `POS NSI`, divisions are summed | yes |
| Last month (SPLY) | a Business Performance Report whose `SPLY-ALL (…)` period is the month before the target month (the month-end report) | optional |

Without a last-month workbook every last-month figure shows as —. The month-end projection is actual sales to date plus separate average-sales forecasts for the remaining Fridays, Saturdays and Sunday–Thursday days, and month-on-month growth is measured only on outlets that have a last-month figure. A failed network refresh never blocks `data.json`; the pages keep the last good `network.json`.

## First-time setup on GitHub

1. Create a new repository (public for testing) and upload everything in this folder, including the `.github` folder.
2. Settings → Actions → General → Workflow permissions: choose **Read and write permissions** and save.
3. Settings → Pages → Build and deployment: Source **GitHub Actions**, then save. (Don't use "Deploy from a branch": the **Deploy dashboard** workflow publishes the site, and a branch deploy would run a second, competing deployment on every push.)
4. Actions → **Refresh data** → **Run workflow**. When it finishes (a few minutes the first time, faster once the download cache is warm), it starts **Deploy dashboard** and the site shows the latest Drive files. Deploys only run when the data actually changed.

## Deploy on Coolify (private)

The same repository deploys to Coolify with the included `Dockerfile`. The container serves the site and downloads the Drive files itself, so it doesn't depend on GitHub Actions. It checks the Drive folders every 5 minutes (`scripts/watch_drive.py`, names and modified times only) and refreshes as soon as a file is added, replaced, renamed or removed, plus a full refresh every hour.

1. In Coolify: **New resource → Application**, pick the GitHub repository (public or private).
2. Build pack: **Dockerfile**. Port: **80**.
3. Environment variables (optional):
   - `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` put a login on the whole site. Leave them empty for no login.
   - `WATCH_MINUTES` sets how often the Drive folders are checked for changes (default 5, day and night); `REFRESH_MINUTES` sets the full backstop refresh (default 60).
   - `REFRESH_FROM` and `REFRESH_TO` set the Dhaka-time hours when refreshes run (default 8 to 23); the first refresh always runs at start-up.
4. Add your domain, then **Deploy**. The first refresh runs as soon as the container starts.

On the Coolify copy, the GitHub "Refresh data" workflow isn't needed. If Coolify redeploys on every push, disable that workflow (Actions → Refresh data → ⋯ → Disable workflow) so it doesn't trigger a redeploy every hour.

## Refresh straight away

GitHub Pages: after uploading a file to Drive, go to Actions → Refresh data → Run workflow.
Coolify: press **Restart** on the application; the refresh runs at start-up.

## Files

- `index.html`, `assets/` — the site
- `scripts/build_data.py` — downloads and reads the sales, KPI, P&L and outlet master files (run `python scripts/build_data.py --local <folder>` to test with local copies in any sub-folders)
- `scripts/network/refresh.py` — downloads the outlet network folder and builds `data/network.json` (standard library only)
- `scripts/av/refresh.py` — builds `data/av.json` for the Availability pages
- `scripts/cw/refresh.py` — downloads the Consumable & Wastage Control folder (Target.txt, Sales-Till, Zone Distribution, CONSUMABLE, WASTAGE) and builds `data/cw.json`
- `.github/workflows/refresh-data.yml` — the hourly refresh
- `data/data.json`, `data/network.json`, `data/network-sync.json`, `data/cw.json`, `data/av.json` — generated data (don't edit by hand)
- `Dockerfile`, `deploy/` — Coolify / Docker packaging (nginx + Drive watch every 5 minutes + hourly refresh + optional login)
