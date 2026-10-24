from app.extensions import db
from app.models import User, ValuationHistory
try:
    from tests.conftest import VALID_PAYLOAD
except ImportError:
    from conftest import VALID_PAYLOAD  # pyright: ignore[reportMissingImports]


def register(client, username='alice', email='alice@example.com', password='s3cret-pass'):
    return client.post('/register', data={
        'username': username, 'email': email, 'password': password,
    })


def login(client, username='alice', password='s3cret-pass', query=''):
    return client.post('/login' + query, data={'username': username, 'password': password})


# ---- authentication -------------------------------------------------------

def test_password_is_hashed(app, client):
    register(client)
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username='alice'))
        assert user.password_hash != 's3cret-pass'
        assert user.check_password('s3cret-pass')


def test_reserved_admin_username_does_not_grant_admin_privileges(app, client):
    """Registration must never grant admin rights based on a chosen username."""
    register(client, username='Vikas10', email='vikas10@example.com')
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username='Vikas10'))
        assert user is not None
        assert user.is_admin is False

    login(client, username='Vikas10')
    response = client.get('/admin')
    assert response.status_code == 302
    assert '/admin' not in response.headers.get('Location', '')


def test_login_success_and_failure(client):
    register(client)
    assert login(client, password='wrong-password').headers['Location'].endswith('/login')
    response = login(client)
    assert response.status_code == 302
    assert client.get('/history').status_code == 200


def test_short_password_rejected(app, client):
    register(client, password='short')
    with app.app_context():
        assert db.session.scalar(db.select(User)) is None


def test_duplicate_username_rejected(app, client):
    register(client)
    register(client, email='other@example.com')
    with app.app_context():
        assert len(db.session.scalars(db.select(User)).all()) == 1



def test_open_redirect_is_blocked(client):
    register(client)
    response = login(client, query='?next=https://evil.example.com/')
    assert 'evil.example.com' not in response.headers['Location']


def test_history_requires_login(client):
    response = client.get('/history')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_admin_is_forbidden_for_regular_users(client):
    register(client)
    login(client)
    response = client.get('/admin')
    assert response.status_code == 302


# ---- prediction API -------------------------------------------------------

def test_api_predict_success(client):
    response = client.post('/api/predict', json=VALID_PAYLOAD)
    assert response.status_code == 200
    data = response.get_json()
    assert data['predicted_price'] == 2.5
    assert data['price_low'] == 2.0 and data['price_high'] == 3.12


def test_api_predict_rejects_bad_input(client):
    assert client.post('/api/predict', json={}).status_code == 400
    assert client.post('/api/predict', json={**VALID_PAYLOAD, 'area': -5}).status_code == 400
    assert client.post('/api/predict', json={**VALID_PAYLOAD, 'region': 'Nowhere'}).status_code == 400
    assert client.post('/api/predict', json={**VALID_PAYLOAD, 'bhk': 2.5}).status_code == 400
    assert client.post('/api/predict', data='not json').status_code == 400


def test_asking_price_verdict(client):
    high = client.post('/api/predict', json={**VALID_PAYLOAD, 'asking_price': 5}).get_json()
    assert high['asking_verdict'] == 'above'
    fair = client.post('/api/predict', json={**VALID_PAYLOAD, 'asking_price': 2.6}).get_json()
    assert fair['asking_verdict'] == 'within'


# ---- pages ----------------------------------------------------------------

def test_predict_form_redirects_and_saves_history(app, client):
    register(client)
    login(client)
    response = client.post('/predict', data={
        'bhk': '2', 'area': '850', 'prop_type': 'Apartment', 'region': 'Andheri West',
        'status': 'Ready to move', 'age': 'New',
    })
    assert response.status_code == 302
    assert 'area=850' in response.headers['Location']
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(ValuationHistory.id))) == 1

    page = client.get(response.headers['Location'])
    assert page.status_code == 200
    assert b'2.50' in page.data


def test_invalid_form_shows_error(client):
    page = client.get('/?bhk=2&area=99999&prop_type=Apartment&region=Andheri+West'
                      '&status=Ready+to+move&age=New', follow_redirects=True)
    assert page.status_code == 200
    assert b'between' in page.data


def test_public_pages_render(client):
    for path in ('/', '/trends', '/how-it-works', '/performance', '/login', '/register', '/healthz'):
        assert client.get(path).status_code == 200, path
    assert client.get('/does-not-exist').status_code == 404


# ---- data support ---------------------------------------------------------

def test_thin_region_gets_warning_and_wider_band(client):
    data = client.post('/api/predict', json={**VALID_PAYLOAD, 'region': 'Nalasopara West'}).get_json()
    assert data['low_data'] is True and data['region_listings'] == 3
    assert data['price_low'] == 1.5 and data['price_high'] == 4.25


def test_well_covered_region_has_no_warning(client):
    data = client.post('/api/predict', json=VALID_PAYLOAD).get_json()
    assert data['low_data'] is False
    assert data['price_low'] == 2.0 and data['price_high'] == 3.12


def test_region_average_needs_enough_listings(app, monkeypatch):
    import pandas as pd
    from app.services import predictor

    def frame(n):
        # Rows differ slightly because real loading drops exact duplicates.
        return pd.DataFrame({
            'region': ['Andheri West'] * n, 'bhk': [2] * n, 'area': [850 + i for i in range(n)],
            'type': ['Apartment'] * n, 'status': ['Ready to move'] * n,
            'final_price': [250.0] * n,
        })

    with app.app_context():
        monkeypatch.setattr(predictor, 'get_dataset', lambda: frame(2))
        few = predictor.predict_price(2, 850, 'Apartment', 'Andheri West', 'Ready to move', 'New')
        assert 'avg_price_cr' not in few['insights']

        monkeypatch.setattr(predictor, 'get_dataset', lambda: frame(8))
        many = predictor.predict_price(2, 850, 'Apartment', 'Andheri West', 'Ready to move', 'New')
        insights = many['insights']
        assert isinstance(insights, dict)
        assert insights['avg_price_cr'] == 2.5 and insights['avg_count'] == 8


def test_api_rejects_unknown_transit_option(client):
    response = client.post('/api/predict', json={**VALID_PAYLOAD, 'transit_proximity': 'metro'})
    assert response.status_code == 400


# ---- compare page ---------------------------------------------------------

COMPARE_QUERY = ('/compare?p1_bhk=2&p1_area=750&p1_region=Andheri+West'
                 '&p2_bhk=3&p2_area=950&p2_region=Nalasopara+West')


def test_compare_page_shows_side_by_side_results(client):
    response = client.get(COMPARE_QUERY)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Side-by-side' in html
    assert 'limited data' in html            # Nalasopara West has only 3 listings


def test_compare_page_uses_defaults_without_parameters(client):
    response = client.get('/compare')
    assert response.status_code == 200
    assert 'Side-by-side' in response.get_data(as_text=True)


def test_compare_page_reports_invalid_input(client):
    response = client.get(COMPARE_QUERY.replace('p2_area=950', 'p2_area=5'))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Property B' in html and 'between 100 and 10000' in html
    assert 'Side-by-side' not in html


# ---- heatmap and assistant APIs ---------------------------------------------

def test_heatmap_api_returns_tiers_and_regions(client):
    response = client.get('/api/heatmap-data')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict) and len(data['tiers']) == 4
    assert data['regions'] == []              # no dataset file in the test config
    assert 'max-age' in response.headers['Cache-Control']



# ---- admin retrain ------------------------------------------------------------

def make_admin(app, username='boss'):
    with app.app_context():
        user = User(username=username, email=f'{username}@example.com', is_admin=True)
        user.set_password('s3cret-pass')
        db.session.add(user)
        db.session.commit()


def test_retrain_requires_admin(app, client):
    assert client.post('/admin/retrain').status_code == 302          # not logged in
    register(client, username='regular', email='reg@example.com')
    login(client, username='regular')
    assert client.post('/admin/retrain').status_code == 403
    assert client.get('/admin/retrain-status').status_code == 403


def test_retrain_start_and_conflict(app, client, monkeypatch):
    from app.routes import admin as admin_routes
    make_admin(app)
    login(client, username='boss')

    monkeypatch.setattr(admin_routes.retrain, 'start_retrain', lambda **kwargs: (True, 'Retraining started.'))
    assert client.post('/admin/retrain').status_code == 202

    monkeypatch.setattr(admin_routes.retrain, 'start_retrain',
                        lambda **kwargs: (False, 'A retrain is already running.'))
    conflict = client.post('/admin/retrain')
    assert conflict.status_code == 409 and 'already running' in conflict.get_json()['error']


def test_retrain_status_and_admin_page(app, client):
    make_admin(app)
    login(client, username='boss')
    status = client.get('/admin/retrain-status').get_json()
    assert status['retrain_state']['status'] in ('idle', 'running', 'completed', 'failed')
    page = client.get('/admin')
    assert page.status_code == 200 and b'Retrain Model Pipeline' in page.data


# ---- security token (CSRF) behaviour -------------------------------------------

FORM_VALUES = {'bhk': '2', 'area': '850', 'prop_type': 'Apartment', 'region': 'Andheri West',
               'status': 'Ready to move', 'age': 'New', 'asking_price': '', 'transit_proximity': 'standard'}


def csrf_token_from(client):
    import re
    html = client.get('/').get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_valuation_form_works_with_a_valid_token(csrf_client):
    token = csrf_token_from(csrf_client)
    response = csrf_client.post('/predict', data={**FORM_VALUES, 'csrf_token': token})
    assert response.status_code == 302 and 'area=850' in response.headers['Location']
    assert b'2.50' in csrf_client.get(response.headers['Location']).data


def test_expired_token_still_shows_the_estimate(csrf_client):
    """A stale page (for example after a server restart) must not lose the result."""
    response = csrf_client.post('/predict', data={**FORM_VALUES, 'csrf_token': 'stale-or-missing'})
    assert response.status_code == 302
    assert 'area=850' in response.headers['Location'] and 'region=Andheri' in response.headers['Location']
    page = csrf_client.get(response.headers['Location'])
    assert b'2.50' in page.data


def test_expired_token_does_not_save_history(app, csrf_client):
    from app.models import ValuationHistory
    csrf_client.post('/predict', data={**FORM_VALUES, 'csrf_token': 'stale-or-missing'})
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(ValuationHistory.id))) == 0


def test_other_forms_still_need_a_token(csrf_client):
    response = csrf_client.post('/login', data={'username': 'x', 'password': 'y'})
    assert response.status_code == 302 and response.headers['Location'].endswith('/')
    assert b'session expired' in csrf_client.get('/').data


def test_json_api_does_not_need_a_token(csrf_client):
    response = csrf_client.post('/api/predict', json=VALID_PAYLOAD)
    assert response.status_code == 200


def test_form_error_is_shown_next_to_the_form(client):
    page = client.get('/?bhk=2&area=99999&prop_type=Apartment&region=Andheri+West'
                      '&status=Ready+to+move&age=New')
    assert b'Could not calculate' in page.data and b'between 100 and 10000' in page.data