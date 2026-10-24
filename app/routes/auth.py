from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db, limiter
from app.models import User

auth_bp = Blueprint('auth', __name__)

MIN_USERNAME_LENGTH = 3
MIN_PASSWORD_LENGTH = 8


def _is_safe_next(target):
    """Allow only same-site redirects (prevents open redirects via ?next=)."""
    if not target:
        return False
    host = urlparse(request.host_url)
    dest = urlparse(urljoin(request.host_url, target))
    return dest.scheme in ('http', 'https') and dest.netloc == host.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config['LOGIN_RATE_LIMIT'], methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user is None or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('auth.login', next=request.args.get('next')))

        login_user(user, remember=True)
        flash(f'Welcome back, {user.username}!', 'success')
        target = request.args.get('next')
        if target is not None and _is_safe_next(target):
            return redirect(target)
        return redirect(url_for('main.index'))

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config['REGISTER_RATE_LIMIT'], methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        error = None
        if len(username) < MIN_USERNAME_LENGTH or len(username) > 64:
            error = f'Username must be {MIN_USERNAME_LENGTH}-64 characters.'
        elif '@' not in email or len(email) > 120:
            error = 'Please enter a valid email address.'
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'

        if error:
            flash(error, 'danger')
            return redirect(url_for('auth.register'))

        user = User(username=username, email=email, is_admin=False)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('That username or email is already registered.', 'danger')
            return redirect(url_for('auth.register'))

        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))