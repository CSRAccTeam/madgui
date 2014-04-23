# encoding: utf-8
"""
Notebook window component for MadGUI (main window).
"""

# force new style imports
from __future__ import absolute_import

# GUI components
import wx
import wx.aui
from wx.py.crust import Crust

# internal
from madgui.util.common import ivar
from madgui.util.plugin import HookCollection
from madgui.core.figure import FigurePanel

# exported symbols
__all__ = ['NotebookFrame']


class NotebookFrame(wx.Frame):

    """
    Notebook window class for MadGUI (main window).
    """

    hook = ivar(HookCollection,
                init='madgui.core.notebook.init',
                menu='madgui.core.notebook.menu')

    def __init__(self, app, show=True):

        """
        Create notebook frame.

        Extends wx.Frame.__init__.
        """

        super(NotebookFrame, self).__init__(
            parent=None,
            title='MadGUI',
            size=wx.Size(800, 600))

        self.app = app
        self.vars = {'views': []}

        # create notebook
        self.panel = wx.Panel(self)
        self.notebook = wx.aui.AuiNotebook(self.panel)
        sizer = wx.BoxSizer()
        sizer.Add(self.notebook, 1, wx.EXPAND)
        self.panel.SetSizer(sizer)
        self.notebook.Bind(
            wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSED,
            self.OnPageClosed,
            source=self.notebook)
        self.notebook.Bind(
            wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE,
            self.OnPageClose,
            source=self.notebook)

        # create menubar and listen to events:
        self.SetMenuBar(self._CreateMenu())

        # Create a command tab
        # TODO: create a log tab/pane
        self._NewCommandTab()

        # show the frame
        self.Show(show)

    def Reserve(self, **vars):
        """
        Return a frame with some global variables.

        If the variables exist within the current frame, a new frame will be
        created. Otherwise, the same frame may be returned.
        """
        for k in vars:
            if k in self.vars:
                frame = self.__class__(self.app)
                frame.vars.update(vars)
                return frame
        self.vars.update(vars)
        return self

    def _CreateMenu(self):
        """Create a menubar."""
        # TODO: this needs to be done more dynamically. E.g. use resource
        # files and/or a plugin system to add/enable/disable menu elements.
        menubar = wx.MenuBar()
        appmenu = wx.Menu()
        menubar.Append(appmenu, '&App')
        # Create menu items
        self.hook.menu(self, menubar)
        appmenu.AppendSeparator()
        appmenu.Append(wx.ID_EXIT, '&Quit', 'Quit application')
        self.Bind(wx.EVT_MENU, self.OnQuit, id=wx.ID_EXIT)
        return menubar

    def AddView(self, view, title):
        """Add new notebook tab for the view."""
        # TODO: remove this method in favor of a event based approach?
        panel = FigurePanel(self.notebook, view)
        self.notebook.AddPage(panel, title, select=True)
        view.plot()
        self.vars['views'].append(view)
        return panel

    def OnPageClose(self, event):
        """Prevent the command tab from closing, if other tabs are open."""
        if event.Selection == 0 and self.notebook.GetPageCount() > 1:
            event.Veto()

    def OnPageClosed(self, event):
        """A page has been closed. If it was the last, close the frame."""
        if self.notebook.GetPageCount() == 0:
            self.Close()
        else:
            del self.vars['views'][event.Selection - 1]

    def OnQuit(self, event):
        """Close the window."""
        self.Close()

    def _NewCommandTab(self):
        """Open a new command tab."""
        self.notebook.AddPage(
            Crust(self.notebook, locals=self.vars),
            "Command",
            select=True)