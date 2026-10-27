# PropVal Insights — Mumbai Property Valuation

PropVal Insights is a Flask web application that estimates Mumbai property prices using a Gradient Boosting model (benchmarked against Random Forest) trained on over 52,000 historical listing records. It features 90% empirical confidence intervals, an interactive Leaflet.js price-tier heatmap, a quick statutory BMC on-road cost & EMI summary, and a personalized user profile dashboard.

## Project layout

```
run.py                       application entry point
app/
  __init__.py                create_app() factory
  config.py                  environment-driven settings
  models.py, cli.py          database models and Flask CLI commands
  routes/                    main.py, auth.py, admin.py
  services/                  prediction, finance, and retraining logic
  templates/ and static/     pages, CSS, JavaScript, and map data
ml_pipeline/train.py         model training pipeline
ml_pipeline/artifacts/       trained model and evaluation metrics
data/raw/                    source property dataset
tests/                       automated tests
```

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python ml_pipeline/train.py
python run.py
```

On macOS/Linux, activate the environment with `source .venv/bin/activate`. The application reads environment variables from a local `.env` file when present. Never commit real credentials or production secrets.

## Admin access

Register a normal account, then grant administrator access explicitly from a trusted local/production command environment:

```bash
flask --app run make-admin <username>
```

Only run this command for an account you have verified belongs to the intended administrator. Do not grant admin rights based on a public username or during normal user registration. To initialize tables manually, run `flask --app run init-db`.

## Tests

```bash
python -m pytest -q
```

The tests use an isolated test database and stub the model for deterministic predictions.

## Production / Render deployment checklist

- Set `APP_ENV=production` and a strong, unique `SECRET_KEY` in the hosting provider's environment settings. Never put the secret in source control or share it in screenshots.
- Configure `DATABASE_URL` to a managed PostgreSQL database for persistent user accounts and valuation history. The app supports the standard `DATABASE_URL` variable.
- If you intentionally use SQLite instead, the database file defaults to `instance/app.db`. A normal Render service filesystem is ephemeral; use a persistent disk mounted at the exact directory used by `INSTANCE_DIR`, and confirm backups and persistence before relying on it. Do not switch database types without a migration/backup plan.
- The app's default `AUTO_CREATE_DB=1` creates missing tables at startup; it is not a replacement for database migrations. Review migration state before changing this setting.
- The default rate-limit store is in-memory. With multiple workers/instances, configure a shared store (for example Redis) using `RATELIMIT_STORAGE_URI`.
- Use the production start command `gunicorn run:app` if that matches the Render service's configured entry point. Confirm the actual service settings before changing them.
- After deployment, verify registration, login/logout, regular-user denial of `/admin`, predictions, valuation history, and the health endpoint. Check Render logs for startup errors and confirm the database survives a restart/redeploy.

Render settings and existing database contents are not changed by repository edits. Back up production data before any database migration or administrator-account changes.

## Model and estimate limitations

- Estimates in regions with few listings are less reliable. The application flags thin regions and widens its estimate range.
- Transit-proximity adjustments, rental yield, growth, and purchase-cost assumptions are assumptions configured by the application, not values directly predicted by the model.
- Stamp-duty estimates use Mumbai/BMC assumptions; rates can differ in other municipal areas. Confirm transaction costs with the relevant authority or a qualified professional before relying on them.
- Stored model scores are evaluation results from the model-training process; retrain and evaluate on current data before making claims about real-world accuracy.

## Dataset source & license

- **Original Dataset:** [Mumbai House Prices](https://www.kaggle.com/datasets/dravidvaishnav/mumbai-house-prices) by **Dravid Vaishnav** on Kaggle (76,038 raw records).
- **Preprocessing & Derived Features:** Added `final_price` (standardized in ₹ Lakhs). During pipeline training (`ml_pipeline/train.py`), region names are standardized, price-per-sqft anomalies outside ₹2,500–₹1,50,000/sq.ft. are filtered out, and exact duplicates across model features are removed, yielding **52,160 clean records**.
- **License:** The source dataset is used under Kaggle's public open dataset terms (CC0: Public Domain). Application source code is licensed under the [MIT License](LICENSE).