import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services import predictor  # noqa: E402


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    AUTO_CREATE_DB = True
    # Point at a folder that has no artifacts so tests control what is loaded.
    ARTIFACTS_DIR = '/nonexistent'
    MODEL_PATH = '/nonexistent/model.pkl'
    SCORES_PATH = '/nonexistent/model_scores.json'
    CATEGORIES_PATH = '/nonexistent/categories.json'
    DATA_PATH = '/nonexistent/data.csv'
    INSTANCE_DIR = tempfile.mkdtemp()      # retrain state/lock files go here


class FakeModel:
    """Stands in for the trained pipeline: always predicts 250 Lakh (2.5 Cr)."""

    def predict(self, frame):
        return [250.0] * len(frame)


class CsrfConfig(TestConfig):
    """Same as TestConfig but with CSRF protection on, like the real server."""
    WTF_CSRF_ENABLED = True


def _prepare(monkeypatch, config_class):
    predictor.clear_caches()
    monkeypatch.setattr(predictor, '_model_for_request', lambda: FakeModel())
    monkeypatch.setattr(predictor, 'get_dataset', lambda: pd.DataFrame())
    monkeypatch.setattr(predictor, 'get_categories', lambda: {
        'types': ['Apartment'], 'regions': ['Andheri West', 'Nalasopara West'],
        'statuses': ['Ready to move'], 'ages': ['New'],
        'region_counts': {'Andheri West': 500, 'Nalasopara West': 3},
    })
    monkeypatch.setattr(predictor, 'get_scores', lambda: {
        'best_model': 'Fake', 'models': {'Fake': 0.9}, 'cv_scores': {'Fake': 0.88},
        'test_scores': {'Fake': 0.87},
        'best_metrics': {'test_r2': 0.87, 'mae_cr': 0.2, 'mape_pct': 12.0,
                         'interval': {'low': 0.8, 'high': 1.25},
                         'interval_sparse': {'low': 0.6, 'high': 1.7},
                         'min_region_listings': 30, 'n_rows': 1000},
    })
    application = create_app(config_class)
    with application.app_context():
        db.drop_all()
        db.create_all()
    return application


@pytest.fixture()
def app(monkeypatch):
    yield _prepare(monkeypatch, TestConfig)


@pytest.fixture()
def csrf_client(monkeypatch):
    """A test client for an app that really checks CSRF tokens."""
    return _prepare(monkeypatch, CsrfConfig).test_client()


@pytest.fixture()
def client(app):
    return app.test_client()


VALID_PAYLOAD = {
    'bhk': 2, 'area': 850, 'prop_type': 'Apartment', 'region': 'Andheri West',
    'status': 'Ready to move', 'age': 'New',
}