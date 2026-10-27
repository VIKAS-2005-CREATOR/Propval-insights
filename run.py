import logging

from app import create_app

app = create_app()

LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}

if __name__ == '__main__':
    # Development server only. In production run: gunicorn run:app
    host = app.config['HOST']
    debug = app.config['DEBUG_MODE']

    if debug and host not in LOOPBACK_HOSTS:
        # The Werkzeug debugger allows remote code execution, so it must never
        # be reachable from other machines.
        logging.getLogger(__name__).warning(
            'Debug mode disabled: it is only allowed when HOST is a loopback address.'
        )
        debug = False

    app.run(debug=debug, host=host, port=app.config['PORT'])
