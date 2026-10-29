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
  services/                  prediction and finance logic
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

- **Environment:** Python Web Service on [Render](https://render.com/).
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn run:app`
- **Database:** SQLite is used by default (`instance/app.db`). To persist user accounts and valuation history across Render restarts/redeploys, you can attach a Render Persistent Disk mounted at `instance/` (or specify the path with `INSTANCE_DIR`).
- **Environment Variables:**
  - `APP_ENV`: Set to `production`
  - `SECRET_KEY`: Set to a strong, random secret key (e.g., generated with `python -c "import secrets; print(secrets.token_hex(32))"`)
- The app's default `AUTO_CREATE_DB=1` automatically creates missing SQLite tables at startup.
- After deployment, verify predictions, price heatmap, valuation PDF generation, and the `/healthz` health endpoint.

## Model and estimate limitations

- Estimates in regions with few listings are less reliable. The application flags thin regions and widens its estimate range.
- Transit-proximity adjustments, rental yield, growth, and purchase-cost assumptions are assumptions configured by the application, not values directly predicted by the model.
- Stamp-duty estimates use Mumbai/BMC assumptions; rates can differ in other municipal areas. Confirm transaction costs with the relevant authority or a qualified professional before relying on them.
- Stored model scores are evaluation results from the model-training process; retrain and evaluate on current data before making claims about real-world accuracy.

## Dataset source & license

- **Original Dataset:** [Mumbai House Prices](https://www.kaggle.com/datasets/dravidvaishnav/mumbai-house-prices) by **Dravid Vaishnav** on Kaggle (76,038 raw records).
- **Preprocessing & Derived Features:** Added `final_price` (standardized in ₹ Lakhs). During pipeline training (`ml_pipeline/train.py`), region names are standardized, price-per-sqft anomalies outside ₹2,500–₹1,50,000/sq.ft. are filtered out, and exact duplicates across model features are removed, yielding **52,160 clean records**.
- **License:** The source dataset is used under Kaggle's public open dataset terms (CC0: Public Domain). Application source code is licensed under the [MIT License](LICENSE).