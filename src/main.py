# main.py - Entry point for Pasar
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw
from .application import PasarApplication


def main(version):
    app = PasarApplication(version=version)
    return app.run(sys.argv)
