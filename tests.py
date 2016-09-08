import logging
import time
from concurrent.futures import Future

import pytest
from PyQt5.QtCore import QTimer

from pyqt_async import QApplication, thread_executor, timing, QThreadExecutor

logging.basicConfig(level=logging.DEBUG, stream=None)


@pytest.fixture()
def app():
    return QApplication([])


def single_shot(app):
    """
    :param QApplication app:
    """

    def decor(func):
        def wrapper(*args, **kwargs):
            def run_func():
                try:
                    result = func(*args, **kwargs)
                finally:
                    app.quit()
                return result

            QTimer.singleShot(0, run_func)
            app.exec_()

        return wrapper

    return decor


def qt_test(func):
    def wrapper(app):
        return single_shot(app)(func)()

    return wrapper


def heavy_computations(seconds=5):
    time.sleep(seconds)
    return seconds


@qt_test
def test_thread_executor():
    seconds = 5
    with timing() as timer:
        future = thread_executor(heavy_computations)(seconds)
    assert isinstance(future, Future)
    assert timer.elapsed < seconds
    time.sleep(seconds / 2)
    assert future.running()
    time.sleep(seconds)
    assert future.done()
    assert future.result() == seconds


@qt_test
def test_thread_executor_map():
    seconds = 5
    iterable = range(seconds)
    with timing() as global_timer:
        with timing() as submit_timer, QThreadExecutor() as executor:
            results = executor.map(heavy_computations, iterable)
        assert submit_timer.elapsed < seconds / 2

        with timing() as fetch_timer:
            results = list(results)
        assert results == list(iterable)

    assert fetch_timer.elapsed < sum(iterable)
    assert global_timer.elapsed < seconds * 1.1


    # @qt_test
    # def test_generator_executor():
    #    pass
