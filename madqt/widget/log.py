# encoding: utf-8
"""
Logging utils.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import logging
import threading
import time
from collections import namedtuple
from functools import partial
from queue import Queue, Empty

from madqt.qt import Qt, QtCore, QtGui
from madqt.core.base import Object, Signal
from madqt.util.collections import List
from madqt.widget.tableview import ColumnInfo, TableView
import madqt.util.font as font


LogRecord = namedtuple('LogRecord', ['time', 'domain', 'text', 'extra'])


class LogWindow(TableView):

    columns = [
        ColumnInfo('Time', lambda record: time.strftime(
            '%H:%M:%S', time.localtime(record.time))),
        ColumnInfo('Domain', 'domain', resize=QtGui.QHeaderView.ResizeToContents),
        ColumnInfo('Text', 'text'),
    ]

    def __init__(self, parent):
        self.records = List()
        super(LogWindow, self).__init__(parent, self.columns, self.records)
        self.horizontalHeader().hide()
        self._setRowResizeMode(QtGui.QHeaderView.ResizeToContents)
        self.setFont(font.monospace())

    def setup_logging(self, level=logging.INFO,
                      fmt='%(name)s: %(message)s'):
        # TODO: MAD-X log should be separate from basic logging
        root = logging.getLogger('')
        manager = logging.Manager(root)
        formatter = logging.Formatter(fmt)
        handler = RecordHandler(self.records)
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.level = level
        # store member variables:
        self._log_manager = manager

    def async_reader(self, domain, stream):
        reader = AsyncRead(stream)
        reader.dataReceived.connect(partial(self.recv_log, reader.queue, domain))

    def recv_log(self, queue, domain):
        lines = list(pop_all(queue))
        if lines:
            text = "\n".join(lines)
            self.records.append(LogRecord(
                time.time(), domain, text, None))


def pop_all(queue):
    while True:
        try:
            x = queue.get_nowait()
        except Empty:
            return
        yield x


class RecordHandler(logging.Handler):

    """Handle incoming logging events by adding them to a list."""

    def __init__(self, records):
        super(RecordHandler, self).__init__()
        self.records = records

    def emit(self, record):
        self.records.append(LogRecord(
            record.created,
            record.levelname,
            self.format(record),
            record,
        ))


class AsyncRead(Object):

    """
    Write to a text control.
    """

    dataReceived = Signal()

    def __init__(self, stream):
        super(AsyncRead, self).__init__()
        self.queue = Queue()
        self.stream = stream
        self.thread = threading.Thread(target=self._readLoop)
        self.thread.start()

    def _readLoop(self):
        # The file iterator seems to be buffered:
        for line in iter(self.stream.readline, b''):
            self.queue.put(line.decode('utf-8', 'replace')[:-1])
            self.dataReceived.emit()
