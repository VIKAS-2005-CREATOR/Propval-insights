"""Service-level tests: finance, predictor, assistant, heatmap and the retrain runner.

These build a tiny Flask app by hand (no database or login), so they run fast.
"""

import json
import os
import sys
import time

import pandas as pd
import pytest
from flask import Blueprint, Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.config import Config  # noqa: E402
from app.services import finance, predictor, retrain  # noqa: E402


class FakeModel:
    """Always predicts 250 Lakh (2.5 Cr)."""

    def predict(self, frame):
        return [250.0] * len(frame)


COLUMNS = ['region', 'bhk', 'area', 'type', 'status', 'age', 'final_price', 'locality']


def listings(region, count, price, bhk=2, area=850):
    # Each row differs slightly, because the loader drops exact duplicates.
    return [{'region': region, 'bhk': bhk, 'area': area + i, 'type': 'Apartment',
             'status': 'Ready to move', 'age': 'New', 'final_price': price + i * 0.001,
             'locality': 'Somewhere'} for i in range(count)]


def make_dataset():
    rows = (listings('Andheri West', 40, 250.0) + listings('Thane West', 40, 120.0, area=900)
            + listings('Vashi', 40, 150.0) + listings('Kharghar', 40, 90.0)
            + listings('Tiny Place', 3, 250.0) + listings('Nalasopara West', 3, 33.0, area=595))
    return pd.DataFrame(rows, columns=COLUMNS)


def make_categories():
    counts = make_dataset()['region'].value_counts().to_dict()
    return {'types': ['Apartment'], 'regions': sorted(counts), 'statuses': ['Ready to move'],
            'ages': ['New'], 'region_counts': {k: int(v) for k, v in counts.items()}}


SCORES = {'best_metrics': {
    'interval': {'low': 0.8, 'high': 1.25}, 'interval_sparse': {'low': 0.6, 'high': 1.7},
    'min_region_listings': 30, 'mape_pct': 12.0, 'n_rows': 1000}}


def build_app(static_folder=None):
    app = Flask('services-test', static_folder=static_folder)
    app.config.from_object(Config)
    blueprint = Blueprint('main', __name__)
    blueprint.add_url_rule('/', 'index', lambda: '')
    app.register_blueprint(blueprint)
    return app


@pytest.fixture()
def svc_app(monkeypatch):
    predictor.clear_caches()
    monkeypatch.setattr(predictor, '_model_for_request', lambda: FakeModel())
    monkeypatch.setattr(predictor, 'get_categories', make_categories)
    monkeypatch.setattr(predictor, 'get_scores', lambda: SCORES)
    monkeypatch.setattr(predictor, 'get_dataset', make_dataset)
    app = build_app()
    with app.test_request_context('/'):
        yield app


def predict(**overrides):
    args = dict(bhk=2, area=850, prop_type='Apartment', region='Andheri West',
                status='Ready to move', age='New')
    args.update(overrides)
    return predictor.predict_price(**args)


# ---- finance --------------------------------------------------------------

def test_format_inr_uses_indian_grouping():
    assert finance.format_inr(999) == '999'
    assert finance.format_inr(15584) == '15,584'
    assert finance.format_inr(1234567) == '12,34,567'
    assert finance.format_inr(26565000) == '2,65,65,000'
    assert finance.format_inr(-1500000) == '-15,00,000'


def test_quick_cost_summary():
    summary = finance.get_quick_cost_summary(2.5)
    assert summary['stamp_duty_reg'] == 1_750_000
    assert summary['total_cost'] == 26_750_000
    assert summary['estimated_emi'] == 173_565

    summary_rupees = finance.get_quick_cost_summary(25_000_000)
    assert summary_rupees == summary


# ---- predictor ------------------------------------------------------------

@pytest.mark.parametrize('overrides', [
    {'asking_price': 'nan'}, {'asking_price': -3}, {'asking_price': 99999},
    {'transit_proximity': 'metro'}, {'prop_type': 'Castle'}, {'status': 'x'},
    {'age': 'x'}, {'region': 'Nowhere'}, {'area': 5}, {'bhk': 2.5}, {'bhk': True},
])
def test_invalid_input_is_rejected(svc_app, overrides):
    assert 'error' in predict(**overrides)


def test_transit_adjustment_is_applied_and_reported(svc_app):
    standard = predict()
    walkable = predict(transit_proximity='walkable')
    extended = predict(transit_proximity='extended')
    assert walkable['predicted_price'] > standard['predicted_price'] > extended['predicted_price']
    assert walkable['transit_adjustment_pct'] == pytest.approx(Config.TRANSIT_PREMIUM_WALKABLE * 100)
    assert extended['transit_adjustment_pct'] == pytest.approx(-Config.TRANSIT_DISCOUNT_EXTENDED * 100)
    assert standard['transit_impact_lakh'] == 0


def test_no_made_up_scores_in_result(svc_app):
    result = predict()
    assert 'value_score' not in result and 'breakdown' not in result


def test_thin_region_flag_and_wider_band(svc_app):
    thin = predict(region='Nalasopara West')
    assert thin['low_data'] is True and thin['region_listings'] == 3
    assert (thin['price_low'], thin['price_high']) == (1.5, 4.25)
    normal = predict()
    assert normal['low_data'] is False and (normal['price_low'], normal['price_high']) == (2.0, 3.12)


def test_regional_average_needs_enough_listings(svc_app):
    assert predict()['insights']['avg_count'] == 40
    assert 'avg_price_cr' not in predict(region='Nalasopara West')['insights']


def test_alternative_regions_ignore_thin_regions(svc_app):
    names = [r['name'] for r in predict(region='Thane West')['insights'].get('alternative_regions', [])]
    assert 'Tiny Place' not in names and 'Nalasopara West' not in names


# ---- heatmap, trends and cache reloading ----------------------------------

@pytest.fixture()
def file_app(tmp_path, monkeypatch):
    predictor.clear_caches()
    static = tmp_path / 'static' / 'data'
    static.mkdir(parents=True)
    (static / 'mumbai_coordinates.json').write_text(json.dumps({
        'Andheri West': [19.13, 72.82], 'Thane West': [19.2, 72.97], 'Tiny Place': [19.0, 72.9]}))
    csv_path = tmp_path / 'data.csv'
    make_dataset().to_csv(csv_path, index=False)
    monkeypatch.setattr(predictor, 'get_scores', lambda: SCORES)
    app = build_app(static_folder=str(tmp_path / 'static'))
    app.config['DATA_PATH'] = str(csv_path)
    with app.test_request_context('/'):
        yield app, csv_path


def test_heatmap_structure_and_cache(file_app):
    app, _ = file_app
    first = predictor.get_heatmap_data()
    assert [t['key'] for t in first['tiers']][0] == 'ultra_luxury'
    by_region = {r['region']: r for r in first['regions']}
    assert set(by_region) == {'Andheri West', 'Thane West', 'Tiny Place'}   # only mapped regions
    assert by_region['Andheri West']['tier'] == 'prime' and by_region['Andheri West']['low_data'] is False
    assert by_region['Tiny Place']['low_data'] is True
    assert predictor.get_heatmap_data()['regions'] is first['regions']       # served from cache


def test_changed_data_file_is_reloaded(file_app):
    app, csv_path = file_app
    before = len(predictor.get_dataset())
    # Exact duplicate rows are dropped, so the total does not change...
    duplicated = pd.concat([make_dataset(), make_dataset().head(5)])
    duplicated.to_csv(csv_path, index=False)
    os.utime(csv_path, (time.time() + 5, time.time() + 5))
    assert len(predictor.get_dataset()) == before
    # ...but genuinely new listings are picked up without a restart.
    extra = pd.concat([make_dataset(), pd.DataFrame(listings('Andheri West', 5, 300.0, area=2000))])
    extra.to_csv(csv_path, index=False)
    os.utime(csv_path, (time.time() + 10, time.time() + 10))
    assert len(predictor.get_dataset()) == before + 5


def test_missing_data_file_gives_empty_results(file_app):
    app, csv_path = file_app
    app.config['DATA_PATH'] = str(csv_path) + '.missing'
    assert predictor.get_dataset().empty
    assert predictor.get_heatmap_data()['regions'] == []



# ---- retrain runner -------------------------------------------------------

def write_script(folder, name, body):
    path = os.path.join(str(folder), name)
    with open(path, 'w') as fh:
        fh.write(body)
    return path


def wait_until_done(instance_dir, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if retrain.get_state(instance_dir)['status'] != 'running':
            return retrain.get_state(instance_dir)
        time.sleep(0.1)
    raise AssertionError('retrain did not finish')


def test_retrain_success_runs_callback_and_releases_lock(tmp_path):
    script = write_script(tmp_path, 'ok.py', 'import time; time.sleep(0.5)')
    calls = []
    started, _ = retrain.start_retrain(str(tmp_path), str(tmp_path), 20, '2', script, lambda: calls.append(1))
    assert started
    again, message = retrain.start_retrain(str(tmp_path), str(tmp_path), 20, '2', script)
    assert again is False and 'already running' in message
    state = wait_until_done(str(tmp_path))
    assert state['status'] == 'completed' and calls == [1]
    assert not os.path.exists(os.path.join(str(tmp_path), retrain.LOCK_NAME))


def test_retrain_failure_is_reported(tmp_path):
    script = write_script(tmp_path, 'bad.py',
                          'import sys; sys.stderr.write("FileNotFoundError: Dataset not found\\n"); sys.exit(1)')
    retrain.start_retrain(str(tmp_path), str(tmp_path), 20, '2', script)
    state = wait_until_done(str(tmp_path))
    assert state['status'] == 'failed' and 'Dataset not found' in state['message']


def test_retrain_timeout_is_reported(tmp_path):
    script = write_script(tmp_path, 'slow.py', 'import time; time.sleep(30)')
    retrain.start_retrain(str(tmp_path), str(tmp_path), 1, '2', script)
    state = wait_until_done(str(tmp_path))
    assert state['status'] == 'failed' and 'timed out' in state['message']


def test_stale_lock_is_cleared_but_a_fresh_one_blocks(tmp_path):
    script = write_script(tmp_path, 'ok.py', 'pass')
    lock = os.path.join(str(tmp_path), retrain.LOCK_NAME)
    open(lock, 'w').write('1')
    assert retrain.start_retrain(str(tmp_path), str(tmp_path), 20, '2', script)[0] is False
    old = time.time() - 5000
    os.utime(lock, (old, old))
    assert retrain.start_retrain(str(tmp_path), str(tmp_path), 20, '2', script)[0] is True
    wait_until_done(str(tmp_path))


def test_orphaned_running_state_is_reported_as_failed(tmp_path):
    with open(os.path.join(str(tmp_path), retrain.STATE_NAME), 'w') as fh:
        json.dump({'status': 'running', 'message': '', 'started_at': 'x', 'finished_at': None}, fh)
    assert retrain.get_state(str(tmp_path))['status'] == 'failed'


# ---- development secret key ---------------------------------------------------

def test_dev_secret_key_is_created_once_and_reused(tmp_path):
    from app.config import _dev_secret_key
    path = str(tmp_path / 'instance' / 'secret_key')
    first = _dev_secret_key(path)
    assert len(first) == 64 and os.path.exists(path)
    assert _dev_secret_key(path) == first          # the same key after a "restart"