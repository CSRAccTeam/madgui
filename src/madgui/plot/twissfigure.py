"""
Utilities to create a plot of some TWISS parameter along the accelerator
s-axis.
"""

__all__ = [
    'PlotSelector',
    'TwissFigure',
]

import math
import logging
from functools import partial
from collections import namedtuple

import numpy as np

from madgui.qt import QtGui, Qt
from madgui.util.signal import Signal
from madgui.util.yaml import load_resource

from madgui.util.qt import load_icon_resource, SingleWindow
from madgui.util.misc import memoize, strip_suffix, cachedproperty
from madgui.util.collections import List
from madgui.util.unit import (
    to_ui, from_ui, get_raw_label, ui_units)
from madgui.plot.scene import (
    SimpleArtist, SceneGraph, ListView, LineBundle, plot_line)
from madgui.widget.dialog import Dialog

import matplotlib.patheffects as pe
import matplotlib.colors as mpl_colors
from matplotlib.ticker import AutoMinorLocator


CONFIG = load_resource(__package__, 'twissfigure.yml')
ELEM_STYLES = CONFIG['element_style']


PlotInfo = namedtuple('PlotInfo', [
    'name',     # internal graph name (e.g. 'beta')
    'title',    # long display name ('Beta function')
    'curves',   # [CurveInfo]
])

CurveInfo = namedtuple('CurveInfo', [
    'name',     # curve name (e.g. 'betx')
    'label',    # y-axis/legend label ('$\beta_x$')
    'style',    # **kwargs for ax.plot
])

UserData = namedtuple('UserData', [
    'name',
    'data',
    'style',
])

MouseEvent = namedtuple('MouseEvent', [
    'button', 'x', 'y', 'axes', 'elem', 'guiEvent'])

KeyboardEvent = namedtuple('KeyboardEvent', [
    'key', 'guiEvent'])


# basic twiss figure

class PlotSelector(QtGui.QComboBox):

    """Widget to choose the displayed graph in a TwissFigure."""

    def __init__(self, scene, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene = scene
        self.scene.graph_changed.connect(self.update_index)
        items = [(l, n) for n, l in scene.get_graphs().items()]
        for label, name in sorted(items):
            self.addItem(label, name)
        self.update_index()
        self.currentIndexChanged.connect(self.change_figure)

    def change_figure(self, index):
        self.scene.set_graph(self.itemData(index))

    def update_index(self):
        self.setCurrentIndex(self.findData(self.scene.graph_name))


class TwissFigure:

    """A figure containing some X/Y twiss parameters."""

    xlim = None
    snapshot_num = 0

    graph_changed = Signal()

    buttonPress = Signal(MouseEvent)
    mouseMotion = Signal(MouseEvent)
    keyPress = Signal(KeyboardEvent)

    def __init__(self, figure, session, matcher):
        self.figure = figure
        self.share_axes = False
        self.session = session
        self.model = session.model()
        self.config = dict(CONFIG, **session.config.get('twissfigure', {}))
        self.matcher = matcher
        self.element_style = self.config['element_style']
        # scene
        self.user_tables = List()
        self.curve_info = List()
        self.hovered_elements = List()
        get_element = self.model.elements.__getitem__
        self.scene_graph = SceneGraph('', [
            SimpleArtist(
                'lattice_elements',
                plot_element_indicators, self.model.elements,
                elem_styles=self.element_style),
            ListView(
                'selected_elements',
                self.model.selection.elements.map(get_element),
                plot_selection_marker, self.model,
                elem_styles=self.element_style),
            ListView(
                'hovered_elements',
                self.hovered_elements.map(get_element),
                plot_selection_marker, self.model,
                elem_styles=self.element_style,
                _effects=_hover_effects, drift_color='#ffffff'),
            ListView(
                'match_constraints',
                self.matcher.constraints,
                plot_constraint, self),
            ListView('twiss_curves', self.curve_info, self.plot_twiss_curve),
            ListView('user_curves', self.user_tables, self.plot_user_curve),
        ], figure)
        self.scene_graph.draw_idle = self.draw_idle
        # style
        self.x_name = 's'
        self.x_label = 's'
        self.x_unit = ui_units.get('s')
        # slots
        self.model.updated.connect(self.on_model_updated)

    def attach(self, plot):
        self.plot = plot
        plot.addTool(InfoTool(plot, self))
        plot.addTool(MatchTool(plot, self, self.matcher))
        plot.addTool(CompareTool(plot, self))

        canvas = plot.canvas
        canvas.mpl_connect('button_press_event', self._on_button_press)
        canvas.mpl_connect('motion_notify_event', self._on_motion_notify)
        canvas.mpl_connect('key_press_event', self._on_key_press)

    def _on_button_press(self, mpl_event):
        self._mouse_event(self.buttonPress, mpl_event)

    def _on_motion_notify(self, mpl_event):
        self._mouse_event(self.mouseMotion, mpl_event)

    def _mouse_event(self, signal, mpl_event):
        if mpl_event.inaxes is None:
            return
        axes = mpl_event.inaxes
        xpos = from_ui(axes.x_name[0], mpl_event.xdata)
        ypos = from_ui(axes.y_name[0], mpl_event.ydata)
        elem = self.get_element_by_mouse_position(axes, xpos)
        event = MouseEvent(mpl_event.button, xpos, ypos,
                           axes, elem, mpl_event.guiEvent)
        signal.emit(event)

    def _on_key_press(self, mpl_event):
        event = KeyboardEvent(mpl_event.key, mpl_event.guiEvent)
        self.keyPress.emit(event)

    graph_name = None

    def set_graph(self, graph_name):
        graph_name = graph_name or self.config['default_graph']
        if graph_name == self.graph_name:
            return
        self.graph_info = self.get_graph_info(graph_name, self.xlim)
        self.graph_name = self.graph_info.name
        self.reset()
        self.graph_changed.emit()

    def reset(self):
        """Reset figure and plot."""
        figure = self.figure
        figure.clear()
        self.scene_graph.on_clear_figure()
        self.scene_graph.enable(False)
        self.curve_info[:] = self.graph_info.curves
        num_curves = len(self.curve_info)
        if num_curves == 0:
            return
        num_axes = 1 if self.share_axes else num_curves
        top_ax = figure.add_subplot(num_axes, 1, 1)
        for i in range(1, num_axes):
            figure.add_subplot(num_axes, 1, i+1, sharex=top_ax)
        for ax in figure.axes:
            ax.grid(True, axis='y')
            ax.x_name = []
            ax.y_name = []
            ax.get_xaxis().set_minor_locator(AutoMinorLocator())
            ax.get_yaxis().set_minor_locator(AutoMinorLocator())
        axes = figure.axes * (num_curves if self.share_axes else 1)
        for ax, info in zip(axes, self.curve_info):
            ax.x_name.append(self.x_name)
            ax.y_name.append(info.name)
            # assuming all curves have the same y units (as they should!!):
            ax.x_unit = self.x_unit
            ax.y_unit = ui_units.get(info.name)
            if not self.share_axes:
                ax.set_ylabel(info.label)
            # replace formatter method for mouse status:
            ax.format_coord = partial(self.format_coord, ax)
        self.figure.axes[-1].set_xlabel(ax_label(self.x_label, self.x_unit))
        self.scene_graph.enable(True)
        self.scene_graph.render()
        if self.share_axes:
            ax = figure.axes[0]
            # TODO: move legend on the outside
            legend = ax.legend(loc='upper center', fancybox=True,
                               shadow=True, ncol=4)
            legend.draggable()

    def draw_idle(self):
        """Draw the figure on its canvas."""
        canvas = self.figure.canvas
        if canvas:
            canvas.draw_idle()

    def destroy(self):
        self.model.updated.disconnect(self.on_model_updated)
        self.scene_graph.destroy()

    def format_coord(self, ax, x, y):
        # TODO: in some cases, it might be necessary to adjust the
        # precision to the displayed xlim/ylim.
        coord_fmt = "{0:.6f}{1}".format
        parts = [coord_fmt(x, get_raw_label(ax.x_unit)),
                 coord_fmt(y, get_raw_label(ax.y_unit))]
        elem = self.get_element_by_mouse_position(ax, x)
        if elem:
            name = strip_suffix(elem.node_name, '[0]')
            parts.insert(0, name.upper())
        return ', '.join(parts)

    def get_element_by_mouse_position(self, axes, pos):
        """Find an element close to the mouse cursor."""
        model = self.model
        elems = model.elements
        elem = model.get_element_by_position(pos)
        if elem is None:
            return None
        # Fuzzy select nearby elements, if they are <= 3px:
        at, L = elem.position, elem.length
        index = elem.index
        x0_px = axes.transData.transform_point((0, 0))[0]
        x2pix = lambda x: axes.transData.transform_point((x, 0))[0]-x0_px
        len_px = x2pix(L)
        if len_px > 5 or elem.base_name == 'drift':
            # max 2px cursor distance:
            edge_px = max(1, min(2, round(0.2*len_px)))
            if index > 0 \
                    and x2pix(pos-at) < edge_px \
                    and x2pix(elems[index-1].length) <= 3:
                return elems[index-1]
            if index < len(elems) \
                    and x2pix(at+L-pos) < edge_px \
                    and x2pix(elems[index+1].length) <= 3:
                return elems[index+1]
        return elem

    def on_model_updated(self):
        """Update existing plot after TWISS recomputation."""
        self.scene_graph.node('lattice_elements').invalidate()
        self.scene_graph.node('twiss_curves').invalidate()
        self.draw_idle()

    def get_curve_by_name(self, name):
        return next((c for c in self.curve_info if c.name == name), None)

    # curves

    def get_graph_info(self, name, xlim):
        """Get the data for a particular graph."""
        # TODO: use xlim for interpolate
        conf = self.config['graphs'][name]
        return PlotInfo(
            name=name,
            title=conf['title'],
            curves=[
                CurveInfo(name, label, style)
                for (name, label, style) in conf['curves']
            ])

    def get_graphs(self):
        """Get a list of graph names."""
        return {name: info['title']
                for name, info in self.config['graphs'].items()}

    def get_graph_columns(self):
        """Get a set of all columns used in any graph."""
        cols = {
            name
            for info in self.config['graphs'].values()
            for (name, label, style) in info['curves']
        }
        cols.add('s')
        cols.update(self.model.twiss()._cache.keys())
        return cols

    @property
    def show_indicators(self):
        return self.scene_graph.node('lattice_elements').enabled()

    @show_indicators.setter
    def show_indicators(self, show):
        if self.show_indicators != show:
            self.scene_graph.node('lattice_elements').enable(show)

    @SingleWindow.factory
    def _curveManager(self):
        from madgui.widget.curvemanager import CurveManager
        widget = CurveManager(self)
        dialog = Dialog(self.plot.window())
        dialog.setWidget(widget, tight=True)
        dialog.setWindowTitle("Curve manager")
        return dialog

    def show_monitor_readouts(self, monitors):
        monitors = [m.lower() for m in monitors]
        elements = self.model.elements
        offsets = self.session.config['online_control']['offsets']
        monitor_data = [
            {'s': elements[r.name].position,
             'x': (r.posx + dx) if r.posx is not None else None,
             'y': (r.posy + dy) if r.posy is not None else None,
             'envx': r.envx,
             'envy': r.envy,
             }
            for r in self.session.control.sampler.readouts_list
            for dx, dy in [offsets.get(r.name.lower(), (0, 0))]
            if r.name.lower() in monitors
        ]
        curve_data = {
            name: np.array([d[name] for d in monitor_data])
            for name in ['s', 'envx', 'envy', 'x', 'y']
        }
        self.add_curve('readouts', curve_data, 'readouts_style')

    def add_curve(self, name, data, style):
        item = UserData(name, data, style)
        for i, c in enumerate(self.user_tables):
            if c.name == name:
                self.user_tables[i] = item
                break
        else:
            self.user_tables.append(item)

    def del_curve(self, name):
        for i, c in enumerate(self.user_tables):
            if c.name == name:
                del self.user_tables[i]
                break

    def plot_twiss_curve(self, ax, info):
        style = with_outline(info.style)
        label = ax_label(info.label, ui_units.get(info.name))
        return plot_curves(ax, self.model.twiss, style, label)

    def plot_user_curve(self, ax, info):
        name, data, style = info
        style = self.config[style] if isinstance(style, str) else style
        return plot_curves(ax, data, style, name)


def plot_curve(axes, data, x_name, y_name, style, label=None):
    """Plot a TWISS parameter curve model into a 2D figure."""
    def get_xydata():
        table = data() if callable(data) else data
        xdata = _get_curve_data(table, x_name)
        ydata = _get_curve_data(table, y_name)
        if xdata is None or ydata is None:
            return (), ()
        return xdata, ydata
    return plot_line(axes, get_xydata, label=label, **style)


def plot_element_indicators(ax, elements, elem_styles=ELEM_STYLES,
                            default_style=None, effects=None):
    """Plot element indicators, i.e. create lattice layout plot."""
    return LineBundle([
        plot_element_indicator(ax, elem, elem_styles, default_style, effects)
        for elem in elements
    ])


def draw_patch(ax, position, length, style):
    at = to_ui('s', position)
    if length != 0:
        patch_w = to_ui('l', length)
        return ax.axvspan(at, at + patch_w, **style)
    else:
        return ax.axvline(at, **style)


def plot_element_indicator(ax, elem, elem_styles=ELEM_STYLES,
                           default_style=None, effects=None):
    """Return the element type name used for properties like coloring."""
    type_name = elem.base_name.lower()
    style = elem_styles.get(type_name, default_style)
    if style is None:
        return LineBundle()

    axes_dirs = {n[-1] for n in ax.y_name} & set("xy")
    # sigmoid flavor with convenient output domain [-1,+1]:
    sigmoid = math.tanh

    style = dict(style, zorder=0)
    styles = [(style, elem.position, elem.length)]

    if type_name == 'quadrupole':
        invert = ax.y_name[0].endswith('y')
        k1 = float(elem.k1) * 100                   # scale = 0.1/m²
        scale = sigmoid(k1) * (1-2*invert)
        style['color'] = ((1+scale)/2, (1-abs(scale))/2, (1-scale)/2)
    elif type_name == 'sbend':
        angle = float(elem.angle) * 180/math.pi     # scale = 1 degree
        ydis = sigmoid(angle) * (-0.15)
        style['ymin'] += ydis
        style['ymax'] += ydis
        # MAD-X uses the condition k0=0 to check whether the attribute
        # should be used (against my recommendations, and even though that
        # means you can never have a kick that exactlycounteracts the
        # bending angle):
        if elem.k0 != 0:
            style = dict(elem_styles.get('hkicker'),
                         ymin=style['ymin'], ymax=style['ymax'])
            styles.append((style, elem.position+elem.length/2, 0))
            type_name = 'hkicker'

    if type_name in ('hkicker', 'vkicker'):
        axis = "xy"[type_name.startswith('v')]
        kick = float(elem.kick) * 10000         # scale = 0.1 mrad
        ydis = sigmoid(kick) * 0.1
        style['ymin'] += ydis
        style['ymax'] += ydis
        if axis not in axes_dirs:
            style['alpha'] = 0.2

    effects = effects or (lambda x: x)
    return LineBundle([
        draw_patch(ax, position, length, effects(style))
        for style, position, length in styles
    ])


class CaptureTool:

    active = False

    def __init__(self, plot):
        self.plot = plot

    # NOTE: always go through setChecked in order to de-/activate!
    # Calling de-/activate directly will leave behind inconsistent state.
    def setChecked(self, checked):
        self.action().setChecked(checked)

    def onToggle(self, active):
        """Update enabled state to match the UI."""
        if active == self.active:
            return
        self.active = active
        if active:
            self.activate()
        else:
            self.deactivate()

    @memoize
    def action(self):
        icon = self.icon
        if isinstance(icon, QtGui.QStyle.StandardPixmap):
            icon = self.plot.style().standardIcon(icon)
        action = QtGui.QAction(icon, self.text, self.plot)
        action.setCheckable(True)
        action.toggled.connect(self.onToggle)
        self.plot.addCapture(self.mode, action.setChecked)
        return action


# Toolbar item for matching


class MatchTool(CaptureTool):

    """
    This toolbar item performs (when checked) simple interactive matching
    via mouse clicks into the plot window.
    """

    # TODO: define matching via config file and fix implementation

    mode = 'MATCH'
    short = 'match constraints'
    text = 'Match for desired target value'

    @cachedproperty
    def icon(self):
        return load_icon_resource('madgui.data', 'target.xpm')

    def __init__(self, plot, scene, matcher):
        """Add toolbar tool to panel and subscribe to capture events."""
        self.plot = plot
        self.scene = scene
        self.model = scene.model
        self.matcher = matcher
        self.matcher.finished.connect(partial(self.setChecked, False))

    def activate(self):
        """Start matching mode."""
        self.matcher.start()
        self.plot.startCapture(self.mode, self.short)
        self.scene.buttonPress.connect(self.onClick)
        self.scene.session.window().viewMatchDialog.create()

    def deactivate(self):
        """Stop matching mode."""
        self.scene.buttonPress.disconnect(self.onClick)
        self.plot.endCapture(self.mode)

    def onClick(self, event):
        """Handle clicks into the figure in matching mode."""
        # If the selected plot has two curves, select the primary/alternative
        # (i.e. first/second) curve according to whether the user pressed ALT:
        index = int(bool(self.scene.share_axes and
                         event.guiEvent.modifiers() & Qt.AltModifier and
                         len(self.scene.curve_info) > 1))
        name = event.axes.y_name[index]
        if event.button == 1:
            return self.add_constraint(event, name)
        if event.button == 2:
            return self.remove_constraint(event, name)

    def remove_constraint(self, event, name):
        """Remove constraint nearest to cursor location."""
        constraints = [c for c in self.matcher.constraints
                       if c.axis == name]
        if constraints:
            cons = min(constraints, key=lambda c: abs(c.pos-event.x))
            elem = cons.elem
            for c in self.scene.curve_info:
                self.removeConstraint(elem, c.name)

    def add_constraint(self, event, name):
        """Add constraint at cursor location."""
        shift = bool(event.guiEvent.modifiers() & Qt.ShiftModifier)
        control = bool(event.guiEvent.modifiers() & Qt.ControlModifier)

        # By default, the list of constraints will be reset. The shift/alt
        # keys are used to add more constraints.
        if not shift and not control:
            self.clearConstraints()

        # add the clicked constraint
        from madgui.model.match import Constraint
        elem, pos = self.model.get_best_match_pos(event.x)
        constraints = [Constraint(elem, pos, name, event.y)]

        if self.matcher.mirror_mode:
            # add another constraint to hold the orthogonal axis constant
            # TODO: should do this only once for each yname!
            constraints.extend([
                Constraint(elem, pos, c.name,
                           self.model.get_twiss(elem.node_name, c.name, pos))
                for c in self.scene.curve_info
                if c.name != name
            ])

        constraints = sorted(constraints, key=lambda c: (c.pos, c.axis))
        self.addConstraints(constraints)

        self.matcher.detect_variables()
        if len(self.matcher.variables) > 0:
            self.matcher.match()

    def addConstraints(self, constraints):
        """Add constraint and perform matching."""
        for constraint in constraints:
            self.removeConstraint(constraint.elem, constraint.axis)
        self.matcher.constraints.extend(constraints)

    def removeConstraint(self, elem, axis):
        """Remove the constraint for elem."""
        indexes = [i for i, c in enumerate(self.matcher.constraints)
                   if c.elem.index == elem.index and c.axis == axis]
        for i in indexes[::-1]:
            del self.matcher.constraints[i]
        # NOTE: we should probably only delete "automatic" variables, but for
        # now let's just assume this is the right thing...
        del self.matcher.variables[:]

    def clearConstraints(self):
        """Remove all constraints."""
        del self.matcher.constraints[:]
        del self.matcher.variables[:]


def plot_constraint(ax, scene, constraint):
    """Draw one constraint representation in the graph."""
    elem, pos, axis, val = constraint
    style = scene.config['constraint_style']
    return LineBundle(ax.plot(
        to_ui('s', pos),
        to_ui(axis, val),
        **style) if axis in ax.y_name else ())


# Toolbar item for info boxes

class InfoTool(CaptureTool):

    """
    Opens info boxes when clicking on an element.
    """

    mode = 'INFO'
    short = 'element info'
    icon = QtGui.QStyle.SP_MessageBoxInformation
    text = 'Show element info boxes'

    def __init__(self, plot, scene):
        """Add toolbar tool to panel and subscribe to capture events."""
        self.plot = plot
        self.scene = scene
        self.model = scene.model
        self.selection = self.model.selection
        self._hovered = None

    def activate(self):
        """Start select mode."""
        self.plot.startCapture(self.mode, self.short)
        self.scene.buttonPress.connect(self.onClick)
        self.scene.mouseMotion.connect(self.onMotion)
        self.scene.keyPress.connect(self.onKey)
        self.plot.canvas.setFocus()

    def deactivate(self):
        """Stop select mode."""
        self.scene.buttonPress.disconnect(self.onClick)
        self.scene.mouseMotion.disconnect(self.onMotion)
        self.scene.keyPress.disconnect(self.onKey)
        self.plot.endCapture(self.mode)
        self.scene.hovered_elements.clear()

    def onClick(self, event):
        """Display a popup window with info about the selected element."""

        if event.elem is None:
            return
        el_id = event.elem.index

        shift = bool(event.guiEvent.modifiers() & Qt.ShiftModifier)
        control = bool(event.guiEvent.modifiers() & Qt.ControlModifier)

        # By default, show info in an existing dialog. The shift/ctrl keys
        # are used to open more dialogs:
        selected = self.selection.elements
        if selected and not shift and not control:
            selected[self.selection.top] = el_id
        elif shift:
            # stack box
            selected.append(el_id)
        else:
            selected.insert(0, el_id)

        # Set focus to parent window, so left/right cursor buttons can be
        # used immediately.
        self.plot.canvas.setFocus()

    def onMotion(self, event):
        el_idx = event.elem.index
        if self._hovered != el_idx:
            self._hovered = el_idx
            self.scene.hovered_elements[:] = [el_idx]

    def onKey(self, event):
        if 'left' in event.key:
            self.advance_selection(-1)
        elif 'right' in event.key:
            self.advance_selection(+1)

    def advance_selection(self, move_step):
        selected = self.selection.elements
        if not selected:
            return
        top = self.selection.top
        elements = self.model.elements
        old_el_id = selected[top]
        old_index = self.model.elements.index(old_el_id)
        new_index = old_index + move_step
        new_el_id = self.model.elements[new_index % len(elements)].index
        selected[top] = new_el_id


def plot_selection_marker(ax, model, el_idx, elem_styles=ELEM_STYLES,
                          _effects=None, drift_color='#eeeeee'):
    """In-figure markers for active/selected elements."""
    elem = model.elements[el_idx]
    default = dict(ymin=0, ymax=1, color=drift_color)
    return plot_element_indicator(
        ax, elem, elem_styles, default, _effects or _selection_effects)


def _selection_effects(style):
    r, g, b = mpl_colors.colorConverter.to_rgb(style['color'])
    h, s, v = mpl_colors.rgb_to_hsv((r, g, b))
    s = (s + 0) / 2
    v = (v + 1) / 2
    return dict(
        style,
        color=mpl_colors.hsv_to_rgb((h, s, v)),
        path_effects=[
            pe.withStroke(linewidth=2, foreground='#000000', alpha=1.0),
        ],
    )


def _hover_effects(style):
    r, g, b = mpl_colors.colorConverter.to_rgb(style['color'])
    h, s, v = mpl_colors.rgb_to_hsv((r, g, b))
    s = (s + 0) / 1.5
    v = (v + 0) / 1.025
    return dict(
        style,
        color=mpl_colors.hsv_to_rgb((h, s, v)),
        path_effects=[
            pe.withStroke(linewidth=1, foreground='#000000', alpha=1.0),
        ],
    )


# Compare tool

class CompareTool:

    """
    Display a precomputed reference curve for comparison.

    The reference curve is NOT visible by default.
    """

    short = 'Show reference curve'
    icon = QtGui.QStyle.SP_DirLinkIcon
    text = 'Load data file for comparison.'

    def __init__(self, plot, scene):
        self.plot = plot
        self.scene = scene

    @memoize
    def action(self):
        icon = self.icon
        if isinstance(icon, QtGui.QStyle.StandardPixmap):
            icon = self.plot.style().standardIcon(icon)
        action = QtGui.QAction(icon, self.text, self.plot)
        action.triggered.connect(self.activate)
        return action

    def activate(self):
        self.scene._curveManager.create()


def plot_curves(ax, data, style, label):
    return LineBundle([
        plot_curve(ax, data, x_name, y_name, style, label=label)
        for x_name, y_name in zip(ax.x_name, ax.y_name)
    ])


def _get_curve_data(data, name):
    try:
        return to_ui(name, data[name])
    except KeyError:
        logging.debug("Missing curve data {!r}, we only know: {}"
                      .format(name, ','.join(data)))


def ax_label(label, unit):
    if unit in (1, None):
        return label
    return "{} [{}]".format(label, get_raw_label(unit))


def with_outline(style, linewidth=6, foreground='w', alpha=0.7):
    return dict(style, path_effects=[
        pe.withStroke(linewidth=linewidth, foreground=foreground, alpha=alpha),
    ])
