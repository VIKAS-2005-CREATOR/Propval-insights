import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from flask_login import current_user
from flask_wtf.csrf import CSRFError

from .cli import register_cli
from .config import Config
from .extensions import csrf, db, limiter, login, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # SQLite file and retrain state/lock files live here.
    os.makedirs(app.config['INSTANCE_DIR'], exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login.init_app(app)
    login.login_view = 'auth.login'
    login.login_message = 'Please log in to access that page.'
    login.session_protection = 'strong'

    from .models import User

    @login.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from .routes.admin import admin_bp
    from .routes.auth import auth_bp
    from .routes.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # {{ amount|inr }} -> 12,34,567 (Indian digit grouping)
    from .services import finance
    app.jinja_env.filters['inr'] = finance.format_inr

    _register_error_handlers(app)
    _register_security_headers(app)
    register_cli(app)

    if app.config.get('AUTO_CREATE_DB'):
        with app.app_context():
            db.create_all()
            # Auto-promote ADMIN_USERNAME if configured
            admin_user = app.config.get('ADMIN_USERNAME')
            if admin_user:
                from app.models import User
                user = User.query.filter_by(username=admin_user).first()
                if user and not user.is_admin:
                    user.is_admin = True
                    db.session.commit()

    return app


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith('/api/'):
            return jsonify(error='Not found.'), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def too_many_requests(_error):
        message = 'Too many requests. Please slow down and try again shortly.'
        if request.path.startswith('/api/'):
            return jsonify(error=message), 429
        flash(message, 'danger')
        return redirect(url_for('main.index'))

    @app.errorhandler(CSRFError)
    def csrf_failed(_error):
        """The security token was missing or expired (for example the server restarted)."""
        if request.path.startswith('/api/'):
            return jsonify(error='Security token missing or expired. Reload the page and try again.'), 400

        if request.endpoint == 'main.predict':
            # An estimate is read-only, so still show it by sending the entered
            # values to the page. Only saving to the history is skipped.
            from .routes.main import FORM_FIELDS
            params = {f: (request.form.get(f) or '').strip() for f in FORM_FIELDS}
            params = {key: value for key, value in params.items() if value}
            if current_user.is_authenticated:
                flash('Your page had expired, so this valuation was not saved to your '
                      'history. Press Calculate again to save it.', 'danger')
            return redirect(url_for('main.index', _anchor='predictor', **params))  # pyright: ignore[reportArgumentType]

        flash('Your session expired. Please reload the page and try again.', 'danger')
        return redirect(url_for('main.index'))

    @app.errorhandler(400)
    def bad_request(error):
        # Covers CSRF failures raised by Flask-WTF.
        if request.path.startswith('/api/'):
            return jsonify(error='Bad request.'), 400
        flash('Your session expired or the form was invalid. Please try again.', 'danger')
        return redirect(url_for('main.index'))


def _register_security_headers(app):
    @app.after_request
    def add_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        return response