from functools import wraps

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import User, ValuationHistory
from app.services import predictor

admin_bp = Blueprint('admin', __name__)


def admin_required(view):
    """Allow only logged-in admins."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
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
    )