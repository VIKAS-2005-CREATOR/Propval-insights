from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template, url_for,
)
from flask_login import current_user, login_required

from app.config import PROJECT_DIR
from app.extensions import db, limiter
from app.models import User, ValuationHistory
from app.services import predictor, retrain

admin_bp = Blueprint('admin', __name__)


def admin_required(view):
    """Allow only logged-in admins (HTML pages get a redirect, APIs get JSON)."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            if view.__name__.startswith('retrain'):
                return jsonify(error='Admins only.'), 403
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('main.index'))
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route('/admin')
@admin_required
def admin():
    users = db.session.scalars(db.select(User).order_by(User.id)).all()

    # One grouped query instead of one COUNT per user.
    rows = db.session.execute(
        db.select(ValuationHistory.user_id, db.func.count(ValuationHistory.id))
        .group_by(ValuationHistory.user_id)
    ).all()
    counts = {r[0]: r[1] for r in rows}

    model_scores = predictor.get_scores()
    return render_template(
        'admin/admin.html',
        users=users,
        counts=counts,
        total_valuations=sum(counts.values()),
        model_scores=model_scores,
        metrics=model_scores.get('best_metrics') or {},
        n_regions=len(predictor.get_categories().get('regions') or []),
        retrain_state=retrain.get_state(current_app.config['INSTANCE_DIR']),
    )


@admin_bp.route('/admin/retrain', methods=['POST'])
@admin_required
@limiter.limit('3 per minute')
def retrain_model():
    """Start a background retrain (a separate process, one job at a time)."""
    cfg = current_app.config
    started, message = retrain.start_retrain(
        instance_dir=cfg['INSTANCE_DIR'],
        project_dir=PROJECT_DIR,
        timeout_seconds=cfg['RETRAIN_TIMEOUT_SECONDS'],
        n_jobs=cfg['RETRAIN_N_JOBS'],
        on_success=predictor.clear_caches,
    )
    if not started:
        return jsonify(error=message), 409
    return jsonify(message=message), 202


@admin_bp.route('/admin/retrain-status')
@admin_required
def retrain_status():
    scores = predictor.get_scores()
    return jsonify(
        retrain_state=retrain.get_state(current_app.config['INSTANCE_DIR']),
        trained_at=scores.get('trained_at'),
        best_model=scores.get('best_model'),
    )