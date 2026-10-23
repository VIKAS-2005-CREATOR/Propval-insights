"""
retrain.py
==========
Runs ml_pipeline/train.py in a separate process so the web server stays
responsive, and keeps the job state in small files so every gunicorn worker
sees the same status.

    start_retrain(...)  - start a job (returns (ok, message))
    get_state()         - current status dict for the admin page

Files (inside the instance folder):
    retrain.lock        - exists while a job is running (created atomically)
    retrain_state.json  - last known status
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

LOCK_NAME = 'retrain.lock'
STATE_NAME = 'retrain_state.json'
IDLE_STATE = {'status': 'idle', 'message': '', 'started_at': None, 'finished_at': None}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _paths(instance_dir):
    return os.path.join(instance_dir, LOCK_NAME), os.path.join(instance_dir, STATE_NAME)


def _write_state(instance_dir, **state):
    _, state_path = _paths(instance_dir)
    tmp = state_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh)
    os.replace(tmp, state_path)


def get_state(instance_dir):
    """Last known job state; a stale 'running' state is reported as failed."""
    lock_path, state_path = _paths(instance_dir)
    try:
        with open(state_path, 'r', encoding='utf-8') as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return dict(IDLE_STATE)
    if state.get('status') == 'running' and not os.path.exists(lock_path):
        # The process that owned the job disappeared (for example a restart).
        state.update(status='failed', message='The retrain job stopped unexpectedly.',
                     finished_at=_now())
    return state


def _acquire_lock(lock_path, timeout_seconds):
    """Create the lock atomically; clear it first if it is clearly stale."""
    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
            except OSError:
                continue
            if age < timeout_seconds + 60:
                return False
            os.remove(lock_path)            # stale: the owner died long ago
            continue
        with os.fdopen(fd, 'w') as fh:
            fh.write(str(os.getpid()))
        return True
    return False


def _run(instance_dir, script_path, cwd, env, timeout_seconds, started_at, on_success):
    lock_path, _ = _paths(instance_dir)
    try:
        completed = subprocess.run(
            [sys.executable, script_path], cwd=cwd, env=env,
            capture_output=True, text=True, timeout=timeout_seconds,
        )
        if completed.returncode == 0:
            on_success()
            _write_state(instance_dir, status='completed', started_at=started_at,
                         finished_at=_now(), message='Model retrained successfully.')
        else:
            tail = (completed.stderr or completed.stdout or '').strip().splitlines()[-3:]
            logger.error('Retrain failed (exit %s): %s', completed.returncode, ' | '.join(tail))
            _write_state(instance_dir, status='failed', started_at=started_at,
                         finished_at=_now(),
                         message='Training failed: ' + (' '.join(tail)[:300] or 'see server log.'))
    except subprocess.TimeoutExpired:
        logger.error('Retrain timed out after %s seconds', timeout_seconds)
        _write_state(instance_dir, status='failed', started_at=started_at, finished_at=_now(),
                     message=f'Training timed out after {max(1, timeout_seconds // 60)} minutes.')
    except Exception:
        logger.exception('Retrain crashed')
        _write_state(instance_dir, status='failed', started_at=started_at, finished_at=_now(),
                     message='Training crashed. See the server log.')
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def start_retrain(instance_dir, project_dir, timeout_seconds, n_jobs='2',
                  script_path=None, on_success=lambda: None):
    """Start a background retrain. Returns (started, message)."""
    os.makedirs(instance_dir, exist_ok=True)
    lock_path, _ = _paths(instance_dir)
    if not _acquire_lock(lock_path, timeout_seconds):
        return False, 'A retrain is already running.'

    script_path = script_path or os.path.join(project_dir, 'ml_pipeline', 'train.py')
    started_at = _now()
    _write_state(instance_dir, status='running', started_at=started_at,
                 finished_at=None, message='Training started.')
    # Limit the CPU the job may use so the website stays usable meanwhile.
    env = {**os.environ, 'TRAIN_N_JOBS': str(n_jobs)}
    thread = threading.Thread(
        target=_run, daemon=True,
        args=(instance_dir, script_path, project_dir, env, timeout_seconds, started_at, on_success),
    )
    thread.start()
    return True, 'Retraining started.'