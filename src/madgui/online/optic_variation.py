"""
Utilities for the optic variation method (Optikvarianzmethode) for beam
alignment.
"""

__all__ = [
    'Corrector',
    'CorrectorWidget',
]

from functools import partial

import numpy as np

from madgui.qt import QtCore, QtGui
from madgui.util.unit import change_unit, get_raw_label
from madgui.widget.tableview import TableItem

from .multi_grid import Corrector as _Corrector, CorrectorWidget as _Widget


class Corrector(_Corrector):
    direct = False


class CorrectorWidget(_Widget):

    ui_file = 'ovm_dialog.ui'

    def get_optic_row(self, i, o) -> ("#", "kL (1)", "kL (2)"):
        return [
            TableItem(i+1),
        ] + [
            TableItem(change_unit(o[par.lower()], info.unit, info.ui_unit),
                      set_value=partial(self.set_optic_value, par))
            for par in self.corrector.selected['optics']
            for info in [self.corrector.optic_params[i]]
        ]

    def get_record_row(self, i, r) -> ("Optic", "Monitor", "X", "Y"):
        return [
            TableItem(self.get_optic_name(r)),
            TableItem(r.monitor),
            TableItem(r.readout.posx, name='posx'),
            TableItem(r.readout.posy, name='posx'),
        ]

    def get_optic_name(self, record):
        for i, optic in enumerate(self.corrector.optics):
            if all(np.isclose(record.optics[k.lower()], v)
                    for k, v in optic.items()):
                return "Optic {}".format(i+1)
        return "custom optic"

    def set_optic_value(self, par, i, o, value):
        o[par.lower()] = value

    def closeEvent(self, event):
        self.bot.cancel()
        super().closeEvent(event)

    num_focus_levels = 6

    def init_controls(self):
        focus_choices = ["F{}".format(i+1)
                         for i in range(self.num_focus_levels)]
        self.read_focus1.addItems(focus_choices)
        self.read_focus2.addItems(focus_choices)
        self.read_focus1.setCurrentText("F1")
        self.read_focus2.setCurrentText("F4")

        corr = self.corrector
        self.tab_optics.set_viewmodel(self.get_optic_row, corr.optics)
        self.tab_records.set_viewmodel(self.get_record_row, corr.records, unit=True)
        for tab in (self.tab_optics, self.tab_records):
            tab.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
            tab.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        super().init_controls()

    def set_initial_values(self):
        self.bot = ProcBot(self, self.corrector)
        self.read_focus()
        self.radio_mode_xy.setChecked(True)
        self.update_status()

    def update_setup(self):
        self.tab_optics.model().titles[1:] = [
            "{}/{}".format(info.name, get_raw_label(info.ui_unit))
            for info in self.corrector.optic_params
        ]
        self._on_update_optics()

    def _on_update_optics(self):
        self.combo_set_optic.clear()
        self.combo_set_optic.addItems([
            "Optic {}".format(i+1)
            for i in range(len(self.corrector.optics))
        ])
        self.btn_set_optic.setEnabled(len(self.corrector.optics) > 0)

    def connect_signals(self):
        super().connect_signals()
        self.btn_read_focus.clicked.connect(self.read_focus)
        self.btn_update.clicked.connect(self.corrector.update_readouts)
        self.btn_record.clicked.connect(self.add_record)
        self.btn_set_optic.clicked.connect(self.set_optic)
        self.tab_records.connectButtons(self.btn_rec_remove, self.btn_rec_clear)
        self.btn_proc_start.clicked.connect(self.bot.start)
        self.btn_proc_abort.clicked.connect(self.bot.cancel)

    def add_record(self, step, shot):
        # TODO: disable "record" button until monitor readouts updated
        # (or maybe until "update" clicked as simpler alternative)
        self.corrector.update_vars()
        self.corrector.update_readouts()
        self.corrector.records.extend(
            self.corrector.current_orbit_records())

    def set_optic(self):
        # TODO: disable "write" button until another optic has been selected
        # or the optic has changed in the DVM
        self.corrector.set_optic(self.combo_set_optic.currentIndex())

    def read_focus(self):
        """Update focus level and automatically load QP values."""
        foci = [self.read_focus1.currentIndex()+1,
                self.read_focus2.currentIndex()+1]

        corr = self.corrector
        ctrl = corr.control
        # TODO: this should be done with a more generic API
        # TODO: do this without beamoptikdll to decrease the waiting time
        dvm = ctrl.backend._dvm
        values, channels = dvm.GetMEFIValue()
        vacc = dvm.GetSelectedVAcc()
        try:
            optics = []
            for focus in foci:
                dvm.SelectMEFI(vacc, *channels._replace(focus=focus))
                optics.append({
                    par.lower(): ctrl.read_param(par)
                    for par in corr.selected['optics']
                })
            corr.optics[:] = optics
            self._on_update_optics()
        finally:
            dvm.SelectMEFI(vacc, *channels)

    data_key = 'optic_variation'

    def update_ui(self):
        super().update_ui()

        running = self.bot.running
        has_fit = self.corrector.fit_results is not None
        self.btn_proc_start.setEnabled(not running)
        self.btn_proc_abort.setEnabled(running)
        self.btn_apply.setEnabled(not running and has_fit)

        self.read_focus1.setEnabled(not running)
        self.read_focus2.setEnabled(not running)
        self.btn_read_focus.setEnabled(not running)
        self.num_shots_wait.setEnabled(not running)
        self.num_shots_use.setEnabled(not running)
        self.radio_mode_x.setEnabled(not running)
        self.radio_mode_y.setEnabled(not running)
        self.radio_mode_xy.setEnabled(not running)
        self.btn_edit_conf.setEnabled(not running)
        self.combo_config.setEnabled(not running)
        self.tab_manual.setEnabled(not running)
        self.ctrl_progress.setRange(0, self.bot.totalops)
        self.ctrl_progress.setValue(self.bot.progress)


class ProcBot:

    def __init__(self, widget, corrector):
        self.widget = widget
        self.corrector = corrector
        self.running = False
        self.model = corrector.model
        self.control = corrector.control
        self.totalops = 100
        self.progress = 0

    def start(self):
        num_ignore = self.widget.num_shots_wait.value()
        num_average = self.widget.num_shots_use.value()
        self.corrector.records.clear()
        self.numsteps = len(self.corrector.optics)
        self.numshots = num_average + num_ignore + 1
        self.num_ignore = num_ignore
        self.totalops = self.numsteps * self.numshots
        self.progress = 0
        self.running = True
        self.widget.update_ui()
        self.log("Started")
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)

    def finish(self):
        self.stop()
        self.widget.update_fit()
        self.log("Finished\n")

    def cancel(self):
        if self.running:
            self.stop()
            self.reset()
            self.log("Cancelled by user.\n")

    def stop(self):
        if self.running:
            self.corrector.set_optic(None)
            self.running = False
            self.timer.stop()
            self.widget.update_ui()

    def reset(self):
        self.corrector.fit_results = None
        self.widget.update_ui()

    def poll(self):
        if not self.running:
            return

        step = self.progress // self.numshots
        shot = self.progress % self.numshots

        if shot == 0:
            self.log("optic {}".format(step))
            self.corrector.set_optic(step)

            self.last_readouts = self.read_monitors()
            self.progress += 1
            self.widget.ctrl_progress.setValue(self.progress)
            return

        readouts = self.read_monitors()
        if readouts == self.last_readouts:
            return
        self.last_readouts = readouts

        self.progress += 1
        self.widget.ctrl_progress.setValue(self.progress)

        if shot <= self.num_ignore:
            self.log('  -> shot {} (ignored)', shot)
            return

        self.log('  -> shot {}', shot)
        self.widget.add_record(step, shot-self.num_ignore-1)

        if self.progress == self.totalops:
            self.finish()

    def read_monitors(self):
        self.corrector.update_readouts()
        return {r.name: r.data for r in self.corrector.readouts}

    def log(self, text, *args, **kwargs):
        self.widget.status_log.appendPlainText(
            text.format(*args, **kwargs))