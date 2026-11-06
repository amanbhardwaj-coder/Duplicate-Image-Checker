# Image Studio — Streamlit inventory image cleaner

A deployable Streamlit app for finding visual duplicates within each inventory row.

## Run locally

Use Python 3.11 or 3.12. From this folder:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Windows: activate with `.venv\Scripts\activate` instead.

## Deploy on Streamlit Community Cloud

1. Upload the contents of this folder to a GitHub repository, including `.streamlit/config.toml`.
2. Go to https://share.streamlit.io and create an app from that repository.
3. Select branch `main`, entrypoint `app.py`, and Python 3.12 in Advanced settings.
4. For Google Sheets access, paste the secrets below into Advanced settings → Secrets. Deploy.
5. Restrict app access to your intended users in Streamlit sharing settings: all visitors to the app use the configured service account's sheet permissions.

CSV mode works without any credentials. No Google Colab authentication is needed.

## Google Sheets setup

Enable the Google Sheets API and Google Drive API in a Google Cloud project. Create a service account and JSON key. Share the target spreadsheet with the service account's `client_email` as Editor.

Add these values to Streamlit Secrets (replace placeholders with the JSON key values):

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
YOUR_KEY_CONTENT
-----END PRIVATE KEY-----
"""
client_email = "your-service-account@your-project-id.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "your-client-x509-cert-url"
```

For local use put the same TOML into `.streamlit/secrets.toml`. Never commit credentials.

## Workflow and behavior

- Choose a UTF-8 CSV or load a Google Sheet. The first row supplies column labels.
- Defaults: stock A, images B:I, processing from row 2, pHash threshold 2, 16 workers.
- Map any number of image columns. Empty cells are skipped.
- Scan, inspect matching pairs, and uncheck candidates you want to retain.
- Download the cleaned CSV, duplicate audit, or URL error report.
- For Sheets, explicitly apply reviewed selections. Only selected duplicate cells are cleared; other cells and formulas remain intact. A current-row check detects edits before writes. This check is not an atomic lock: avoid concurrent editing while applying.
- Download errors preserve their original URL. EXIF orientation and transparency are normalized before hashing. Downloads have retries, timeouts, and a 20 MB limit. Hashes are cached in memory (up to 10,000 URLs), so repeated URLs are reused.
- Updates use 500-cell batches. A partial failure displays the confirmed count; reload and rescan before retrying.
- Source values are not numerically coerced; CSV export preserves values such as `3.0` and leading zeros. CSV quoting/line endings may be normalized.
- pHash is a visual heuristic. Similar jewelry variants may match; review candidates before applying. First matching image by column order is retained.
- Unlike the original script, scan results are exported as a separate audit rather than overwriting column J.
- Long scans run in the current Streamlit session; keep it open until completion. Jobs are not durable across app restarts. A fresh scan can safely be run after a restart.

## Files

`app.py`: frontend and Sheets workflow. `engine.py`: threaded image scanner and CSV helpers. `requirements.txt`: deployment dependencies. `test_engine.py`: scanner regression checks.
