import click

from .extensions import db
from .models import User


def register_cli(app):
    """Register custom `flask` commands."""

    @app.cli.command('init-db')
    def init_db():
        """Create all database tables."""
        db.create_all()
        click.echo('Database tables created.')

    @app.cli.command('make-admin')
    @click.argument('username')
    def make_admin(username):
        """Grant admin rights to an existing user."""
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user is None:
            raise click.ClickException(f'No user named {username!r}.')
        user.is_admin = True
        db.session.commit()
        click.echo(f'{username} is now an admin.')
