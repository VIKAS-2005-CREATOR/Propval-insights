from typing import Any, cast
from flask import (
    Blueprint, current_app, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import csrf, db, limiter
from app.models import ValuationHistory
from app.services import finance, predictor

main_bp = Blueprint('main', __name__)

FORM_FIELDS = ('bhk', 'area', 'prop_type', 'region', 'status', 'age',
               'asking_price', 'transit_proximity')
DEFAULTS = {
    'bhk': '2', 'area': '850', 'prop_type': 'Apartment', 'region': 'Andheri West',
    'status': 'Ready to move', 'age': 'New', 'asking_price': '', 'transit_proximity': 'standard',
}
SELECT_FIELDS = {
    'prop_type': 'types', 'region': 'regions', 'status': 'statuses', 'age': 'ages',
}
COMPARE_FIELDS = ('bhk', 'area', 'prop_type', 'region', 'status', 'age')
HISTORY_LIMIT = 200


def _form_values(source, categories, submitted):
    """Values used to fill the form (submitted input, or sensible defaults)."""
    values = {}
    for field in FORM_FIELDS:
        raw = (source.get(field) or '').strip()
        values[field] = raw if (submitted or raw) else DEFAULTS[field]

    if not submitted:
        # Make sure default selections actually exist in the trained categories.
        for field, key in SELECT_FIELDS.items():
            options = categories.get(key) or []
            if options and values[field] not in options:
                values[field] = options[0]
    return values


def _predict_from(values):
    return predictor.predict_price(
        values['bhk'], values['area'], values['prop_type'], values['region'],
        values['status'], values['age'], values.get('asking_price'),
        values.get('transit_proximity'),
    )


@main_bp.route('/')
def index():
    categories = predictor.get_categories()
    model_scores = predictor.get_scores()

    submitted = 'area' in request.args
    form = _form_values(request.args, categories, submitted)

    context = {
        'categories':   categories,
        'model_scores': model_scores,
        'metrics':      model_scores.get('best_metrics') or {},
        'form':         form,
    }

    if submitted:
        result = _predict_from(form)
        if 'error' in result:
            # Shown inside the results panel; a banner at the top of the page
            # would be scrolled out of view by the #predictor anchor.
            context['form_error'] = result['error']
        else:
            context.update(result)
            context['money'] = finance.summary(result['predicted_price'])

    return render_template('dashboard/index.html', **context)


@main_bp.route('/predict', methods=['POST'])
@limiter.limit(lambda: current_app.config['PREDICT_RATE_LIMIT'])
def predict():
    """Validate, store history, then redirect (Post/Redirect/Get)."""
    values = {field: (request.form.get(field) or '').strip() for field in FORM_FIELDS}
    result = _predict_from(values)

    if 'error' not in result and current_user.is_authenticated:
        res_data = cast(dict[str, Any], result)
        inputs = cast(dict[str, Any], res_data['inputs'])
        try:
            db.session.add(ValuationHistory(
                bhk=inputs['bhk'],
                carpet_area=inputs['area'],
                prop_type=inputs['prop_type'],
                region=inputs['region'],
                status=inputs['status'],
                age=inputs['age'],
                predicted_price=float(res_data['predicted_price']),
                user_id=current_user.id,
            ))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Could not save valuation history')

    # Errors are reported by index(), which re-validates the same values.
    params = {key: value for key, value in values.items() if value}
    return redirect(url_for('main.index', _anchor='predictor', **cast(Any, params)))


@main_bp.route('/trends')
def trends():
    return render_template('dashboard/trends.html', market_data=predictor.get_market_trends())


def _compare_defaults(categories):
    """Two well-covered regions and the first available option for the other fields."""
    regions = categories.get('regions') or []
    counts = categories.get('region_counts') or {}
    busiest = sorted(regions, key=lambda name: counts.get(name, 0), reverse=True)
    first = busiest[0] if busiest else DEFAULTS['region']
    second = busiest[1] if len(busiest) > 1 else first

    def first_of(key, fallback):
        options = categories.get(key) or []
        return options[0] if options else fallback

    common = {
        'prop_type': first_of('types', DEFAULTS['prop_type']),
        'status':    first_of('statuses', DEFAULTS['status']),
        'age':       first_of('ages', DEFAULTS['age']),
    }
    return (
        {**common, 'bhk': '2', 'area': '750', 'region': first},
        {**common, 'bhk': '3', 'area': '950', 'region': second},
    )


def _compare_side(prefix, defaults):
    values = {}
    for field in COMPARE_FIELDS:
        raw = (request.args.get(f'{prefix}_{field}') or '').strip()
        values[field] = raw or defaults[field]
    result = predictor.predict_price(
        values['bhk'], values['area'], values['prop_type'], values['region'],
        values['status'], values['age'],
    )
    if 'error' in result:
        return values, None, str(result['error'])
    res_data = cast(dict[str, Any], result)
    res_data['money'] = finance.summary(res_data['predicted_price'])
    return values, res_data, None


@main_bp.route('/compare')
def compare():
    """Compare two properties. Uses GET so a comparison can be shared as a link."""
    categories = predictor.get_categories()
    defaults_a, defaults_b = _compare_defaults(categories)
    p1, p1_data, p1_error = _compare_side('p1', defaults_a)
    p2, p2_data, p2_error = _compare_side('p2', defaults_b)

    return render_template(
        'dashboard/compare.html',
        categories=categories, p1=p1, p2=p2,
        p1_data=p1_data, p2_data=p2_data, p1_error=p1_error, p2_error=p2_error,
    )


@main_bp.route('/how-it-works')
def how_it_works():
    return render_template('dashboard/how_it_works.html')


@main_bp.route('/performance')
def performance():
    return render_template('dashboard/performance.html', model_scores=predictor.get_scores())


@main_bp.route('/history')
@login_required
def history():
    valuations = (
        current_user.valuations
        .order_by(ValuationHistory.timestamp.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    return render_template('history/history.html', valuations=valuations)


@main_bp.route('/api/predict', methods=['POST']) # type: ignore
@csrf.exempt
@limiter.limit(lambda: current_app.config['PREDICT_RATE_LIMIT'])
def api_predict():
    """JSON API. It is stateless and uses no cookies, so CSRF does not apply."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Send a JSON object as the request body.'), 400

    result = predictor.predict_price(
        data.get('bhk'), data.get('area'), data.get('prop_type'),
        data.get('region'), data.get('status'), data.get('age'),
        data.get('asking_price'), data.get('transit_proximity'),
    )
    return jsonify(result), (400 if 'error' in result else 200)


@main_bp.route('/api/heatmap-data')
@limiter.limit(lambda: current_app.config['HEATMAP_RATE_LIMIT'])
def api_heatmap_data():
    """Price tiers and per-region rates for the Leaflet heatmap overlay."""
    response = jsonify(predictor.get_heatmap_data())
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response



@main_bp.route('/healthz')
def healthz():
    return jsonify(status='ok')


@main_bp.route('/about')
def about():
    categories = predictor.get_categories()
    num_regions = len(categories.get('regions', []))
    num_listings = sum(categories.get('region_counts', {}).values())

    context = {
        'num_regions': num_regions,
        'num_listings': num_listings,
    }
    return render_template('public/about.html', **context)

@main_bp.route('/terms')
def terms():
    return render_template('public/terms.html')

@main_bp.route('/privacy')
def privacy():
    return render_template('public/privacy.html')