# Web Scraper Alert

Maharashtra property auction scraper and dashboard. Data is collected from:

| Source | URL |
|--------|-----|
| BAANKNET | https://baanknet.com/property-listing |
| eAuctions India | Maharashtra city pages |
| BankAuctions.in | https://bankauctions.in/ |
| FindAuction.in | https://findauction.in/ (MH cities) |
| MHADA eAuction | https://eauction.mhada.gov.in/ |
| MSTC / IBAPI | https://www.mstcecommerce.com/auctionhome/ibapi/index.jsp |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python scraper.py
```

Outputs JSON to `data/property_listings.json`.

## Email notifications

Set these environment variables to enable email alerts:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `EMAIL_FROM`
- `EMAIL_TO` (default in workflow is `gondgesagar.2025@gmail.com`)

Example (PowerShell):

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="youraccount@gmail.com"
$env:SMTP_PASS="your_app_password"
$env:EMAIL_FROM="youraccount@gmail.com"
$env:EMAIL_TO="gondgesagar.2025@gmail.com"
python scraper.py
```

## Change detection

The scraper stores state in `.state/state.json` and only sends email when
new or changed listings are detected.

## GitHub Actions

Workflow: `.github/workflows/scrape.yml` runs every 5 minutes.

To set up GitHub Actions:

1. Push this repository to GitHub
2. Go to **Settings > Secrets and variables > Actions**
3. Add the following repository secrets:
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USER`
   - `SMTP_PASS`
   - `EMAIL_FROM`

The workflow will automatically:
- Run on schedule (every 5 minutes)
- Install dependencies and Playwright
- Run the scraper
- Commit changes to `data/property_listings.json` if there are updates
- Sync `docs/data/property_listings.json` for the dashboard
- Send email alerts via configured SMTP

You can also manually trigger the workflow from the **Actions** tab.

## Local Testing

Test the dashboard locally before pushing to GitHub / GitHub Pages:

```bash
# Generate fresh data (only listings with valid detail URLs are saved)
python scraper.py

# Serve the dashboard from docs/ on localhost
python serve_local.py

# Optional: custom port and open browser automatically
python serve_local.py --port 8080 --open
```

Open **http://localhost:8000** in your browser. The dashboard hides postings without a real property URL (no empty links, ads, or blog/contact pages).

Press `Ctrl+C` to stop the server.

## Dashboard (GitHub Pages)

The static dashboard lives in `docs/`. To publish it:

1. Go to **Settings > Pages**
2. Set **Source** to **Deploy from a branch**
3. Select **Branch: main** and **Folder: /docs**

The dashboard reads data from `docs/data/property_listings.json`. The workflow
syncs it automatically after each scrape. Use the **Refresh data** button on
the page to fetch the latest JSON.
