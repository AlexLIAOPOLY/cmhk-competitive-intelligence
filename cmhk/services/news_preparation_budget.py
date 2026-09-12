"""Bounded preparation lets the delivery lane replace expensive failed stories."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import fcntl
import time

_DEADLINE = ContextVar('personal_news_preparation_deadline', default=None)


def deadline(seconds=180):
    return min(time.monotonic() + seconds, _DEADLINE.get() or float('inf'))


def expired():
    return _DEADLINE.get() is not None and time.monotonic() >= _DEADLINE.get()


@contextmanager
def preparation_window(seconds):
    token = _DEADLINE.set(deadline(seconds))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def candidate_budget():
    return preparation_window(180)


def bounded_preparation(function):
    @wraps(function)
    def run(*args, **kwargs):
        token = _DEADLINE.set(deadline(600))
        try:
            return function(*args, **kwargs)
        finally:
            _DEADLINE.reset(token)
    return run


def acquire_story_lock(handle):
    if _DEADLINE.get() is None:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return
    until = deadline(5)
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= until:
                raise TimeoutError('该新闻由其他准备任务处理中，本次换选其他新闻')
            time.sleep(.05)
