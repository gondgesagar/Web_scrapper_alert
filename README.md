# Web Scraper Alert

Basic scraper framework for BAANKNET property listings.

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

Workflow: `.github/workflows/scrape.yml` runs every 6 hours (0, 6, 12, 18 UTC).

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
- Run on schedule (every 6 hours)
- Install dependencies and Playwright
- Run the scraper
- Commit changes to `data/property_listings.json` if there are updates
- Send email alerts via configured SMTP

You can also manually trigger the workflow from the **Actions** tab.
