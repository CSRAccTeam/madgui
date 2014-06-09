#!/usr/bin/env python
# encoding: utf-8
"""
Installation script for MadGUI.

Usage:
    python setup.py install
"""

from setuptools import setup

setup(
    name='madgui',
    version='0.2',
    description='GUI for beam simulation using MadX via PyMad',
    long_description=open('README.rst').read(),
    author='Thomas Gläßle',
    author_email='t_glaessle@gmx.de',
    maintainer='Thomas Gläßle',
    maintainer_email='t_glaessle@gmx.de',
    url='https://github.com/coldfix/madgui',
    packages=['madgui'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Topic :: Scientific/Engineering :: Medical Science Apps.',
        'Topic :: Scientific/Engineering :: Physics',
    ],
    license='MIT',
    test_suite='nose.collector',
    install_requires=[
        'cern-pymad==0.8',
        'docopt',
        'matplotlib',
        'numpy',
        'pydicti>=0.0.4',
        'PyYAML',
        'Unum>=4.0',
        'wxPython>=2.8',
    ],
    entry_points="""
        [gui_scripts]
        madgui = madgui.core.app:App.main

        [madgui.core.app.init]
        mainframe = madgui.core.notebook:NotebookFrame

        [madgui.core.figure.init]
        matchtool = madgui.component.matchtool:MatchTool
        selecttool = madgui.component.selecttool:SelectTool
        comparetool = madgui.component.comparetool:CompareTool
        statusbar = madgui.component.lineview:UpdateStatusBar.create
        drawelements = madgui.component.lineview:DrawLineElements.create

        [madgui.component.matching.start]
        drawconstraints = madgui.component.lineview:DrawConstraints

        [madgui.core.notebook.menu]
        openmodel = madgui.component.openmodel:OpenModelDlg.connect_menu
        plainopen = madgui.component.plainopen:connect_menu
        changetwiss = madgui.component.changetwiss:TwissDialog.connect_menu
        beamdlg = madgui.component.beamdlg:BeamDialog.connect_menu

        [madgui.component.model.show]
        lineview = madgui.component.lineview:EnvView.create
        xyview = madgui.component.lineview:XYView.create
        settitle = madgui.core.notebook:set_frame_title

        [madgui.models]
        lhc = madgui.component.lhcmodels:locator
    """,
    package_data={
        'madgui': ['resource/*']
    }
)
