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

# 3rd party
from cern.cpymad.madx import Madx

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

        self._claimed = False
        madx = Madx()
        libmadx = madx._libmadx

        self.app = app
        self.vars = {'views': [],
                     'madx': madx,
                     'libmadx': libmadx}

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
        self.CreateStatusBar()

        # create menubar and listen to events:
        self.SetMenuBar(self._CreateMenu())

        # Create a command tab
        # TODO: create a log tab/pane
        self._NewCommandTab()

        # show the frame
        self.Show(show)

    def Claim(self):
        """
        Claim ownership of a frame.

        If this frame is already claimed, returns a new frame. If this frame
        is not claimed, sets the status to claimed and returns self.

        This is used to prevent several models/files to be opened in the
        same frame (using the same Madx instance) with the menu actions.
        """
        if self._claimed:
            return self.__class__(self.app).Claim()
        else:
            self._claimed = True
            return self

    def _CreateMenu(self):
        """Create a menubar."""
        # TODO: this needs to be done more dynamically. E.g. use resource
        # files and/or a plugin system to add/enable/disable menu elements.
        menubar = self.menubar = wx.MenuBar()
        appmenu = wx.Menu()
        seqmenu = wx.Menu()
        menubar.Append(appmenu, '&App')
        menubar.Append(seqmenu, '&Sequence')
        # Create menu items
        self.hook.menu(self, menubar)
        appmenu.AppendSeparator()
        appmenu.Append(wx.ID_EXIT, '&Quit', 'Quit application')
        self.Bind(wx.EVT_MENU, self.OnQuit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_UPDATE_UI, self.OnUpdateMenu, menubar)
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

    def OnUpdateMenu(self, event):
        self.menubar.EnableTop(1, 'control' in self.vars)

    def _NewCommandTab(self):
        """Open a new command tab."""
        self.notebook.AddPage(
            Crust(self.notebook, locals=self.vars),
            "Command",
            select=True)
