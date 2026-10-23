<<<<<<< HEAD
# PropVal Insights - Mumbai Property Valuation

Flask web app that estimates Mumbai flat prices with a scikit-learn model, trained on
historical listing data. It also has a price heatmap (OpenStreetMap + Leaflet), a
two-property comparison page, and purchase-cost and rent scenarios.

## Layout

```
run.py                       development entry point
app/
  __init__.py                create_app() factory
  config.py                  all settings (read from .env)
  models.py  cli.py  extensions.py
  routes/                    main.py, auth.py, admin.py
  services/
    predictor.py             validation, prediction, heatmap, trends (cached)
    finance.py               stamp duty, registration, rent, growth (shared numbers)
    retrain.py               background retraining (separate process, lock file)
  templates/  static/        css/, js/ (index.js), data/
ml_pipeline/train.py         trains the model, writes ml_pipeline/artifacts/
data/raw/mumbai_properties.csv
tests/
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate              # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # macOS/Linux: cp .env.example .env, then set SECRET_KEY
python ml_pipeline/train.py         # about 3-4 minutes
python run.py
```

Create an admin: register normally, then `flask --app run make-admin <username>`.
Production: `APP_ENV=production`, set `SECRET_KEY`, run `gunicorn run:app`.

## Good to know

- **Estimates for thin regions are rough.** Many regions have only a few listings. The
  region is target-encoded, regions with fewer than 30 listings show a "limited data"
  warning and a wider error band, and regional averages need at least 5 comparable listings.
- **Assumptions are labelled.** Station-proximity adjustment, rental yield, growth and
  stamp-duty rates are settings in `.env`, not model output. Stamp duty uses Mumbai (BMC)
  rates; other municipal areas can differ.
- **Retraining** from the admin page runs `ml_pipeline/train.py` in a separate process
  and swaps the new model in atomically. The app notices the new files by their
  modification time, so no restart is needed.
- **Passwords are securely hashed** with Werkzeug (scrypt / pbkdf2).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
=======
# mumbai-property-predictor
PropVal Insights is a machine learning-based web application that predicts property prices in Mumbai using historical property data and relevant features.
>>>>>>> c6f5be65880ba7df6ab798e5b37741fcf0be1746
