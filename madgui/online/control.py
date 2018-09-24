"""
Plugin that integrates a beamoptikdll UI into MadGUI.
"""

import logging

import numpy as np

from madgui.core.base import Object
from madgui.util.misc import SingleWindow
from madgui.util.collections import Bool, List, CachedList

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
        self.model = frame.model
        self.readouts = List()
        # menu conditions
        self.is_connected = Bool(False)
        self.can_connect = ~self.is_connected
        self.has_sequence = self.is_connected & self.model
        self.loader_name = None
        self._settings = frame.config.online_control.settings
        self._on_model_changed()

    # menu handlers

    def connect(self, name, loader):
        logging.info('Connecting online control: {}'.format(name))
        self.model.changed.connect(self._on_model_changed)
        self._on_model_changed()
        self._plugin = loader.load(self._frame, self._settings)
        self._plugin.connect()
        self._frame.context['csys'] = self._plugin
        self.is_connected.set(True)
        self.loader_name = name

    def disconnect(self):
        self._settings = self.export_settings()
        self._frame.context.pop('csys', None)
        self._plugin.disconnect()
        self._plugin = None
        self.is_connected.set(False)
        self.loader_name = None
        self.model.changed.disconnect(self._on_model_changed)
        self._on_model_changed()

    def _on_model_changed(self):
        model = self.model()
        elems = self.is_connected() and model and model.elements or ()
        read_monitor = lambda i, n: MonitorReadout(n, self.read_monitor(n))
        self.monitors = CachedList(read_monitor, [
            elem.name
            for elem in elems
            if elem.base_name.lower().endswith('monitor')
            or elem.base_name.lower() == 'instrument'
        ])

    def export_settings(self):
        if hasattr(self._plugin, 'export_settings'):
            return self._plugin.export_settings()
        return self._settings

    def get_knobs(self):
        """Get list of :class:`ParamInfo`."""
        if not self.model():
            return []
        return list(filter(
            None, map(self._plugin.param_info, self.model().globals)))

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
        model, live = self.model(), self._plugin
        widget.data = [
            SyncParamItem(
                knob, live.read_param(knob.name), model.read_param(knob.name))
            for knob in self.get_knobs()
        ]
        widget.data_key = 'dvm_parameters'
        self._show_dialog(widget, apply)

    def read_all(self, knobs=None):
        live = self._plugin
        self.model().write_params([
            (knob.name, live.read_param(knob.name))
            for knob in knobs or self.get_knobs()
        ], "Read params from online control")

    def write_all(self, knobs=None):
        model = self.model()
        self.write_params([
            (knob.name, model.read_param(knob.name))
            for knob in knobs or self.get_knobs()
        ])

    def on_read_beam(self):
        # TODO: add confirmation dialog
        self.read_beam()

    def read_beam(self):
        self.model().update_beam(self._plugin.get_beam())

    def read_monitor(self, name):
        return self._plugin.read_monitor(name)

    @SingleWindow.factory
    def monitor_widget(self):
        """Read out SD values (beam position/envelope)."""
        from madgui.online.diagnostic import MonitorWidget
        return MonitorWidget(self, self.model(), self._frame)

    @SingleWindow.factory
    def orm_measure_widget(self):
        """Measure ORM for later analysis."""
        from madgui.widget.dialog import Dialog
        from madgui.online.orm_analysis import MeasureWidget
        widget = MeasureWidget(self, self.model(), self._frame)
        dialog = Dialog(self._frame)
        dialog.setWidget(widget)
        dialog.setWindowTitle("ORM scan")
        return dialog

    def _show_dialog(self, widget, apply=None, export=True):
        from madgui.widget.dialog import Dialog
        dialog = Dialog(self._frame)
        if export:
            dialog.setExportWidget(widget, self._frame.folder)
            dialog.serious.updateButtons()
        else:
            dialog.setWidget(widget, tight=True)
        # dialog.setWindowTitle()
        if apply is not None:
            dialog.accepted.connect(apply)
        dialog.show()
        return dialog

    def on_correct_multi_grid_method(self):
        import madgui.online.multi_grid as module
        from madgui.widget.dialog import Dialog

        varyconf = self.model().data.get('multi_grid', {})
        selected = next(iter(varyconf))

        self.read_all()

        method = module.Corrector(self, varyconf)
        method.setup(selected)

        widget = module.CorrectorWidget(method)
        dialog = Dialog(self._frame)
        dialog.setWidget(widget, tight=True)
        dialog.show()

    def on_correct_optic_variation_method(self):
        import madgui.online.optic_variation as module
        from madgui.widget.dialog import Dialog

        varyconf = self.model().data.get('optic_variation', {})
        selected = next(iter(varyconf))

        self.read_all()

        method = module.Corrector(self, varyconf)
        method.setup(selected)

        widget = module.CorrectorWidget(method)
        dialog = Dialog(self._frame)
        dialog.setWidget(widget, tight=True)
        dialog.show()

    # helper functions

    def write_params(self, params):
        write = self._plugin.write_param
        for param, value in params:
            write(param, value)
        self._plugin.execute()

    def read_param(self, name):
        return self._plugin.read_param(name)


class MonitorReadout:

    def __init__(self, name, values):
        self.name = name
        self.data = values
        self.posx = values.get('posx')
        self.posy = values.get('posy')
        self.envx = values.get('envx')
        self.envy = values.get('envy')
        self.valid = (self.envx is not None and self.envx > 0 and
                      self.envy is not None and self.envy > 0 and
                      not np.isclose(self.posx, -9.999) and
                      not np.isclose(self.posy, -9.999))
