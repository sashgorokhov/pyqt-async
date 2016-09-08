"""
Asynchronous tools for PyQt apps.

This module allows you to write an asynchronous code with ease of a single decorator.
"""

import collections
import functools
import logging
import time
from concurrent import futures
from contextlib import contextmanager

try:
    from PyQt4 import QtCore
    from PyQt4.QtGui import QApplication
except ImportError:
    from PyQt5 import QtCore
    from PyQt5.QtWidgets import QApplication


logger = logging.getLogger(__name__)


def _fobj(obj):
    """Format object str representation"""
    return str(hex(id(obj))) + " " + str(obj.__class__.__qualname__)


# For logging purposes
class _Timer(object):
    start = None
    end = None

    @property
    def elapsed(self):
        if self.end is None:
            raise ValueError(".end is not set")
        return self.end - self.start

    def __init__(self, start):
        self.start = start

    def __str__(self):
        return '{:.2f}s'.format(self.elapsed)


@contextmanager
def timing():
    """
    :rtype: _Timer
    """
    start = time.time()
    timer = _Timer(start)
    try:
        yield timer
    except:
        pass
    end = time.time()
    timer.end = end


@contextmanager
def object_timer(obj, msg=None):
    try:
        with timing() as timer:
            yield timer
    finally:
        try:
            logger.info("%s completed in %s: %s", _fobj(obj), timer, msg)
        except ReferenceError:
            logger.exception()


def process_events():
    """Default event processing function"""
    with timing() as timer:
        QApplication.instance().processEvents()
    logger.debug("Processed events in {}".format(timer))


class BaseThread(QtCore.QThread):
    """
    You have to store links for all running threads, otherwise they will be killed unexpectedly.
    """
    def __init__(self, *args, **kwargs):
        super(BaseThread, self).__init__(*args, **kwargs)

    def __del__(self):
        logger.warning("%s will be destroyed", _fobj(self))
        self.wait()


class FutureThread(BaseThread):
    """
    QThread with support for working with futures

    :param concurrent.futures.Future future: future object of thread
    :param finished_future: signal called when thread is finished with future object as argument
    :param finished_future_result: signal called when thread is finished with future result as argument
    """
    finished_future = QtCore.pyqtSignal("PyQt_PyObject")
    finished_future_result = QtCore.pyqtSignal("PyQt_PyObject")

    def __init__(self, *args, **kwargs):
        super(FutureThread, self).__init__(*args, **kwargs)
        self.future = futures.Future()
        self.future.add_done_callback(self.finished_future.emit)
        self.future.add_done_callback(lambda future: self.finished_future_result.emit(future.result()))

    def start(self, *args, **kwargs):
        """
        Starts thread and returns a future object

        :rtype: concurrent.futures.Future
        """
        super(FutureThread, self).start(*args, **kwargs)
        logger.info("%s started", _fobj(self))
        return self.future

    def run(self):
        """
        Main future logic. Do not override this, or it won't work as expected.
        """
        if not self.future.set_running_or_notify_cancel():
            logger.info("%s cancelled", _fobj(self))
            return
        try:
            with object_timer(self, "work done"):
                result = self.work()
        except Exception as e:
            self.future.set_exception(e)
            logger.exception("%s got an exception", _fobj(self))
            return
        else:
            self.future.set_result(result)
            logger.info("%s got result", _fobj(self))
            # return result

    def work(self):
        """
        Override this to do your stuff. Returned data will be set to future result,
        any error raised will be set to future exception
        """
        # TODO: support generators
        raise NotImplementedError


class ExecutableThread(FutureThread):
    def __init__(self, func, *args, **kwargs):
        """
        Executes given func in a separate thread.

        :param callable func:
        :param args:
        :param kwargs:
        """
        super(ExecutableThread, self).__init__()
        self.work = functools.partial(func, *args, **kwargs)


class QThreadExecutor(futures.Executor):
    """
    Asynchronous executor for working with QThreads through ExecutableThread.
    """
    def submit(self, fn, *args, **kwargs):
        executable_thread = ExecutableThread(fn, *args, **kwargs)
        return executable_thread.start()


def thread_executor(func):
    """
    Decorator for running decorated function in separate thread.
    """
    def wrapper(*args, **kwargs):
        with QThreadExecutor() as executor:
            return executor.submit(func, *args, **kwargs)
    return wrapper


class GeneratorThread(QtCore.QObject):
    """
    Sweet. Executes given generator asynchronously in current event loop using Qt's signal mechanism.

    :param collections.Generator generator:
    :param concurrent.futures.Future future:
    """
    _execute_next = QtCore.pyqtSignal()

    def __init__(self, generator):
        """
        :param collections.Generator generator:
        """
        if not isinstance(generator, collections.Generator):
            raise ValueError('%s is not Generator' % generator)

        super(GeneratorThread, self).__init__()

        self.generator = generator
        self.future = futures.Future()
        self.results = list()

        self._execute_next.connect(self.next)
        self._execute_next.emit()

    def process_events(self):
        """
        Process Qt gui events to prevent interface freezes.
        """
        process_events()

    def _send_future(self, future):
        """
        :param concurrent.futures.Future future:
        """
        logger.info("%s %s sending: %s", _fobj(self), str(self.generator), str(future))
        if future._exception:
            self.generator.throw(future.exception())
        else:
            self.generator.send(future.result())

    def send(self, future):
        """
        Sends future result or exception to generator.

        :param concurrent.futures.Future future:
        """
        try:
            self._send_future(future)
        except StopIteration:
            return
        self._execute_next.emit()
        logger.debug("%s %s scheduled next()", _fobj(self), str(self.generator))

    def handle_result(self, result):
        """
        Handle generator result (yield'ed data)

        :return bool: True to continue iteration, False to skip
        """
        if isinstance(result, ExecutableThread):
            result.finished_future.connect(lambda *args, **kwargs: self.send(*args, **kwargs))  # BUG
            result.start()
            return
        if isinstance(result, futures.Future):
            result.add_done_callback(self.send)
            return
        return True

    def next(self):
        """
        Executes next iteration of generator.
        """
        logger.debug("%s %s executing next()", _fobj(self), str(self.generator))
        if self.future.cancelled() or (not self.future.running() and not self.future.set_running_or_notify_cancel()):
            logger.info("%s %s cancelled", _fobj(self), str(self.generator))
            return
        self.process_events()
        try:
            with object_timer(self.generator, "next() done"):
                result = next(self.generator)
        except StopIteration:
            self.future.set_result(self.results)
            logger.info("%s %s got StopIteration", _fobj(self), str(self.generator))
            return
        except Exception as e:
            self.future.set_exception(e)
            logger.exception("%s %s got an exception", _fobj(self), str(self.generator))
            raise
        else:
            if self.handle_result(result):
                self._execute_next.emit()
                self.results.append(result)
                logger.debug("%s %s scheduled next()", _fobj(self), str(self.generator))


class GeneratorExecutor(futures.Executor):
    """
    Asynchronous executor for working with GeneratorThread.
    """
    def submit(self, fn, *args, **kwargs):
        generator_thread = GeneratorThread(fn(*args, **kwargs))
        return generator_thread.future


def generator_executor(func):
    """
    Decorator for running generator function through GeneratorThread.
    """
    def wrapper(*args, **kwargs):
        with GeneratorExecutor() as executor:
            return executor.submit(func, *args, **kwargs)
    return wrapper


    # class BaseTask(object):
    #    pass
    #
    #
    # class Task(BaseTask):
    #    pass
    #
    #
    # class ListTask(BaseTask):
    #    def __init__(self, *args):
    #        pass
    #
    #
    # class ParallelListTask(BaseTask):
    #    pass
    #
    #
    # class MapTask(BaseTask):
    #    pass
