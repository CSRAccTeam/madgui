"""
Plugin that integrates a beamoptikdll UI into MadGUI.
"""

from madgui.qt import QtGui
from madgui.core.base import Object
from madgui.util.misc import SingleWindow
from madgui.util.collections import Bool

# TODO: catch exceptions and display error messages
# TODO: automate loading DVM parameters via model and/or named hook


class Control(Object):

    """
    Plugin class for MadGUI.
    """

    def __init__(self, frame):
        """
        Add plugin to the frame.

        Add a menu that can be used to connect to the online control. When
        connected, the plugin can be used to access parameters in the online
        database. This works only if the corresponding parameters were named
        exactly as in the database and are assigned with the ":=" operator.
        """
        super().__init__()
        self._frame = frame
        self._plugin = None
        # menu conditions
        self.is_connected = Bool(False)
        self.can_connect = ~self.is_connected
        self.has_sequence = self.is_connected & frame.has_model

    # menu handlers

    def connect(self, loader):
        self._plugin = loader.load(self._frame)
        self._plugin.connect()
        self._frame.context['csys'] = self._plugin
        self.is_connected.set(True)

    def disconnect(self):
        self._frame.context.pop('csys', None)
        self._plugin.disconnect()
        self._plugin = None
        self.is_connected.set(False)

    def toggle_jitter(self):
        # I know…
        self._plugin._dvm._lib.jitter = not self._plugin._dvm._lib.jitter

    def get_knobs(self):
        """Get list of :class:`ParamInfo`."""
        if not self._model:
            return []
        return list(filter(
            None, map(self._plugin.param_info, self._model.globals)))

    # TODO: unify export/import dialog -> "show knobs"
    # TODO: can we drop the read-all button in favor of automatic reads?
    # (SetNewValueCallback?)
    def on_read_all(self):
        """Read all parameters from the online database."""
        from madgui.online.dialogs import ImportParamWidget
        self._show_sync_dialog(ImportParamWidget(), self.read_all)

    def on_write_all(self):
        """Write all parameters to the online database."""
        from madgui.online.dialogs import ExportParamWidget
        self._show_sync_dialog(ExportParamWidget(), self.write_all)

    def _show_sync_dialog(self, widget, apply):
        from madgui.online.dialogs import SyncParamItem
        model, live = self._model, self._plugin
        widget.data = [
            SyncParamItem(
                knob, live.read_param(knob.name), model.read_param(knob.name))
            for knob in self.get_knobs()
        ]
        widget.data_key = 'dvm_parameters'
        self._show_dialog(widget, apply)

    def read_all(self, knobs=None):
        live = self._plugin
        self._model.write_params([
            (knob.name, live.read_param(knob.name))
            for knob in knobs or self.get_knobs()
        ])

    def write_all(self, knobs=None):
        model = self._model
        self.write_params([
            (knob.name, model.read_param(knob.name))
            for knob in knobs or self.get_knobs()
        ])

    def on_read_beam(self):
        # TODO: add confirmation dialog
        self.read_beam()

    def read_beam(self):
        self._model.set_beam(self._plugin.get_beam())

    def read_monitor(self, name):
        return self._plugin.read_monitor(name)

    @SingleWindow.factory
    def monitor_widget(self):
        """Read out SD values (beam position/envelope)."""
        from madgui.online.diagnostic import MonitorWidget
        widget = MonitorWidget(self, self._model, self._frame)
        widget.show()
        return widget

    def _show_dialog(self, widget, apply=None, export=True):
        from madgui.widget.dialog import Dialog
        dialog = Dialog(self._frame)
        if export:
            dialog.setExportWidget(widget, self._frame.folder)
        else:
            dialog.setWidget(widget, tight=True)
        # dialog.setWindowTitle()
        if apply is not None:
            dialog.applied.connect(apply)
        dialog.show()
        return dialog

    def on_correct_multi_grid_method(self):
        import madgui.correct.multi_grid as module
        from madgui.widget.dialog import Dialog

        varyconf = self._model.data.get('multi_grid', {})
        selected = next(iter(varyconf))

        self.read_all()

        method = module.Corrector(self, varyconf)
        method.setup(selected)

        widget = module.CorrectorWidget(method)
        dialog = Dialog(self._frame)
        dialog.setWidget(widget, tight=True)
        dialog.show()

    def on_correct_optic_variation_method(self):
        import madgui.correct.optic_variation as module
        from madgui.widget.dialog import Dialog
        varyconf = self._model.data.get('optic_variation', {})

        self.read_all()
        self._frame.open_graph('orbit')

        model = self._model
        elements = model.elements

        select = module.SelectWidget(elements, varyconf)
        dialog = Dialog(self._frame)
        dialog.setExportWidget(select, self._frame.folder)
        dialog.exec_()
        if dialog.result() != QtGui.QDialog.Accepted:
            return

        method = module.Corrector(self, *select.get_data())
        widget = module.CorrectorWidget(method)
        dialog = Dialog(self._frame)
        dialog.setWidget(widget)
        dialog.show()

    def on_emittance_measurement(self):
        from madgui.online.emittance import EmittanceDialog
        dialog = EmittanceDialog(self)
        dialog.show()
        return dialog

    # helper functions

    @property
    def _model(self):
        """Return the online control."""
        return self._frame.model

    def write_params(self, params):
        write = self._plugin.write_param
        for param, value in params:
            write(param, value)
        self._plugin.execute()
