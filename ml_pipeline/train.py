"""
train.py
========
Train and save the best ML pipeline for PropVal Insights.

Run from the project root:
    python ml_pipeline/train.py

Outputs (in ml_pipeline/artifacts/ unless ARTIFACTS_DIR is set):
    model.pkl          - best sklearn model, refit on ALL data
    model_scores.json  - train / CV / held-out TEST metrics + error intervals
    categories.json    - dropdown values and listing counts per region

Prices are in Lakhs (final_price); the app converts to Crores.

Why the region is target-encoded
--------------------------------
The dataset has hundreds of regions and many have only a handful of listings.
One-hot encoding gives tree models almost nothing to learn from for those
regions, so their estimates collapse toward a generic average. A smoothed
target encoding shrinks small regions toward the global mean and keeps large
regions close to their own average price.
"""

import os
import json
from datetime import datetime, timezone

import joblib  # pyright: ignore[reportMissingImports]
import numpy as np  # pyright: ignore[reportMissingImports]
import pandas as pd

from sklearn.pipeline        import Pipeline
from sklearn.compose         import ColumnTransformer, TransformedTargetRegressor
from sklearn.preprocessing   import (
    StandardScaler, OneHotEncoder, TargetEncoder,
)
from sklearn.linear_model    import LinearRegression, Ridge, Lasso
from sklearn.ensemble        import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics         import r2_score, mean_absolute_error, mean_squared_error

try:
    from dotenv import load_dotenv
    load_dotenv()          # read the same .env file the Flask app uses
except ImportError:
    pass

# Same variable names and defaults as app/config.py, so the trainer writes
# exactly where the app reads.
_HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR   = os.path.dirname(_HERE)
DATA_PATH     = os.environ.get(
    'DATA_PATH', os.path.join(PROJECT_DIR, 'data', 'raw', 'mumbai_properties.csv'))
ARTIFACTS_DIR = os.environ.get(
    'ARTIFACTS_DIR', os.path.join(_HERE, 'artifacts'))
MODEL_PATH    = os.path.join(ARTIFACTS_DIR, 'model.pkl')
SCORES_PATH   = os.path.join(ARTIFACTS_DIR, 'model_scores.json')
CATS_PATH     = os.path.join(ARTIFACTS_DIR, 'categories.json')

FEATURES  = ['bhk', 'area', 'type', 'region', 'status', 'age']
TARGET    = 'final_price'
NUM_FEATS = ['bhk', 'area']
CAT_FEATS = ['type', 'status', 'age']      # low-cardinality: one-hot encoded
SEED      = 42
# CPU cores used for training (-1 = all). The admin retrain button lowers this
# so the website stays responsive while a model trains.
N_JOBS    = int(os.environ.get('TRAIN_N_JOBS', '-1'))

# Regions with fewer training listings than this get a wider error band and a
# "limited data" warning in the app.
MIN_REGION_LISTINGS = 30


def make_pipeline(estimator):
    """Preprocessing + estimator, with the skewed price modelled on a log scale."""
    preprocessor = ColumnTransformer(transformers=[
        ('num', StandardScaler(), NUM_FEATS),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CAT_FEATS),
        ('region', Pipeline([
            ('encode', TargetEncoder(target_type='continuous', smooth='auto',
                                     cv=5, random_state=SEED)),
            ('scale',  StandardScaler()),
        ]), ['region']),
    ])
    # The log transform wraps the WHOLE pipeline so the target encoder also
    # sees log prices.
    return TransformedTargetRegressor(
        regressor=Pipeline([('preprocessor', preprocessor), ('regressor', estimator)]),
        func=np.log1p, inverse_func=np.expm1,
    )


def error_band(actual, predicted):
    """90% band as multipliers of the prediction (actual / predicted ratios)."""
    ratio = np.asarray(actual) / np.asarray(predicted)
    return {
        'low':  round(float(np.quantile(ratio, 0.05)), 3),
        'high': round(float(np.quantile(ratio, 0.95)), 3),
    }


def _atomic_write(path, writer):
    """Write to a temp file in the same folder, then swap it in with os.replace.

    A reader (the web app) never sees a half-written file.
    """
    tmp = path + '.tmp'
    writer(tmp)
    os.replace(tmp, path)


def train_and_save_model():
    print(f"\n{'=' * 64}\n PropVal Insights - Model Training\n{'=' * 64}\n")
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    if not os.path.exists(DATA_PATH):
        # Raise (instead of just printing) so callers and the admin retrain
        # button can tell that nothing was trained.
        raise FileNotFoundError(f'Dataset not found at: {DATA_PATH}')

    df = pd.read_csv(DATA_PATH)
    print(f"[INFO] Raw rows:   {len(df):,}")

    # -- Clean (duplicates removed so CV/test scores are not inflated) -------
    df = df.dropna(subset=FEATURES + [TARGET]).copy()

    # 1. Standardise string formatting to prevent duplicate regions in dropdown
    for col in CAT_FEATS + ['region']:
        df[col] = df[col].astype(str).str.strip()

    df['region'] = (
        df['region']
        .str.title()
        .str.replace(r'\s+', ' ', regex=True)
        .str.replace('Sector-', 'Sector ', regex=False)
        .str.replace('Dombivli', 'Dombivali', regex=False)
        .str.replace('Ville Parle', 'Vile Parle', regex=False)
    )
    df = df[~df['region'].isin(['Mumbai', 'Sector', 'Unknown'])]

    # 2. Filter basic invalid numbers and extreme price-per-sqft typos
    df = df[(df[TARGET] > 0) & (df['area'] > 0) & (df['bhk'] > 0)]
    price_per_sqft = (df[TARGET] * 100_000) / df['area']
    df = df[(price_per_sqft >= 2500) & (price_per_sqft <= 150000)]
    df = df.drop_duplicates(subset=FEATURES + [TARGET]).reset_index(drop=True)
    print(f"[INFO] Clean rows: {len(df):,}")

    X, y = df[FEATURES], df[TARGET]

    categories = {
        'types':         sorted(X['type'].unique().tolist()),
        'regions':       sorted(X['region'].unique().tolist()),
        'statuses':      sorted(X['status'].unique().tolist()),
        'ages':          sorted(X['age'].unique().tolist()),
        'region_counts': {k: int(v) for k, v in X['region'].value_counts().items()},
    }

    sparse_regions = sum(1 for n in categories['region_counts'].values() if n < MIN_REGION_LISTINGS)
    print(f"[INFO] Regions: {len(categories['regions'])} "
          f"({sparse_regions} have fewer than {MIN_REGION_LISTINGS} listings)")

    # -- Hold out a test set: never used for model selection ----------------
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEED)

    candidates = {
        'Linear Regression': LinearRegression(),
        'Ridge Regression':  Ridge(alpha=10.0),
        'Lasso Regression':  Lasso(alpha=0.001, max_iter=10000),  # log-target => small alpha
        'Random Forest':     RandomForestRegressor(
                                 n_estimators=200, max_depth=20,
                                 min_samples_leaf=2, random_state=SEED, n_jobs=N_JOBS),
        'Gradient Boosting': GradientBoostingRegressor(
                                 n_estimators=200, learning_rate=0.05,
                                 max_depth=5, random_state=SEED),
    }

    train_r2, cv_r2, test_r2 = {}, {}, {}
    print(f"{'Model':<20}{'Train R2':>10}{'CV R2':>10}{'Test R2':>10}")
    print('-' * 50)

    best_name, best_cv = '', -np.inf
    for name, est in candidates.items():
        pipe = make_pipeline(est)
        cv = cross_val_score(pipe, X_tr, y_tr, cv=5, scoring='r2', n_jobs=N_JOBS).mean()
        pipe.fit(X_tr, y_tr)
        train_r2[name] = round(pipe.score(X_tr, y_tr), 4)
        cv_r2[name]    = round(cv, 4)
        test_r2[name]  = round(pipe.score(X_te, y_te), 4)
        print(f"{name:<20}{train_r2[name]:>10.4f}{cv_r2[name]:>10.4f}{test_r2[name]:>10.4f}")
        if cv > best_cv:                       # select on CV only, not on test
            best_cv, best_name = cv, name

    print('-' * 50)
    print(f"[BEST] {best_name} (CV R2 = {best_cv:.4f})")

    # -- Honest error numbers for the winner (held-out test set) ------------
    best = make_pipeline(candidates[best_name]).fit(X_tr, y_tr)
    pred = best.predict(X_te)
    mae_lakh = float(mean_absolute_error(y_te, pred))
    ape      = np.abs(y_te.values - pred) / y_te.values
    mape     = float(np.mean(ape) * 100)

    # Separate bands for well-covered and thinly-covered regions
    support = X_te['region'].map(X_tr['region'].value_counts()).fillna(0).values
    sparse  = support < MIN_REGION_LISTINGS
    interval = error_band(y_te.values, pred)
    interval_sparse = None
    if sparse.sum() >= 50:
        interval_sparse = error_band(y_te.values[sparse], pred[sparse])
    sparse_mape = float(np.mean(ape[sparse]) * 100) if sparse.any() else None

    print(f"[TEST] R2={r2_score(y_te, pred):.4f}  MAE={mae_lakh:.1f} Lakh  MAPE={mape:.1f}%  "
          f"90% band x{interval['low']} .. x{interval['high']}")
    if interval_sparse:
        print(f"[TEST] Thin regions ({int(sparse.sum())} test rows): MAPE={sparse_mape:.1f}%  "
              f"band x{interval_sparse['low']} .. x{interval_sparse['high']}")

    # -- Final model: refit on all data --------------------------------------
    final = make_pipeline(candidates[best_name]).fit(X, y)

    rmse_lakh = float(np.sqrt(mean_squared_error(y_te, pred)))
    result = {
        'best_model':  best_name,
        'trained_at':  datetime.now(timezone.utc).strftime('%d %b %Y'),
        'models':      train_r2,      # kept so existing templates keep working
        'cv_scores':   cv_r2,
        'test_scores': test_r2,
        'metrics': {
            'r2':        round(float(r2_score(y_te, pred)), 4),
            'test_r2':   round(float(r2_score(y_te, pred)), 4),
            'mae_lakh':  round(mae_lakh, 2),
            'rmse_lakh': round(rmse_lakh, 2),
            'mae_cr':    round(mae_lakh / 100.0, 3),
            'rmse_cr':   round(rmse_lakh / 100.0, 3),
            'mape_pct':  round(mape, 2),
        },
        'best_metrics': {
            'test_r2':             round(float(r2_score(y_te, pred)), 4),
            'mae_cr':              round(mae_lakh / 100.0, 3),
            'mape_pct':            round(mape, 2),
            'interval':            interval,
            'interval_sparse':     interval_sparse,
            'min_region_listings': MIN_REGION_LISTINGS,
            'n_rows':              len(df),
        },
        'prediction_interval': {
            'confidence': 0.90,
            'low_multiplier': interval['low'],
            'high_multiplier': interval['high'],
            'sparse_low_multiplier': interval_sparse['low'] if interval_sparse else interval['low'],
            'sparse_high_multiplier': interval_sparse['high'] if interval_sparse else interval['high'],
        },
    }

    def _dump_json(data):
        def writer(tmp):
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2)
        return writer

    # Everything is written only after training succeeded, model first.
    _atomic_write(MODEL_PATH, lambda tmp: joblib.dump(final, tmp, compress=3))
    _atomic_write(CATS_PATH, _dump_json(categories))
    _atomic_write(SCORES_PATH, _dump_json(result))
    print(f"[DONE] Saved model + scores to {ARTIFACTS_DIR}\n")


if __name__ == '__main__':
    train_and_save_model()