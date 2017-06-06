# encoding: utf-8
"""
Info boxes to display element detail.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

from madqt.qt import QtCore, QtGui

from madqt.widget.params import ParamTable


__all__ = [
    'ElementInfoBox',
]


class ElementInfoBox(ParamTable):

    def __init__(self, segment, el_id, **kwargs):
        super(ElementInfoBox, self).__init__([], segment.utool, **kwargs)

        self.segment = segment
        self.el_id = el_id
        self.segment.updated.connect(self.update)

    def closeEvent(self, event):
        self.segment.updated.disconnect(self.update)
        event.accept()

    @property
    def el_id(self):
        return self._el_id

    @el_id.setter
    def el_id(self, name):
        self._el_id = name
        self.update()

    @property
    def element(self):
        return self.segment.elements[self.el_id]

    def update(self):
        """
        Update the contents of the managed popup window.
        """
        self.datastore = self.segment.get_elem_ds(self.el_id)
        super(ElementInfoBox, self).update()
        self.resizeColumnsToContents()
