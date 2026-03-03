# main.py - Entry point for Pasar
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw
from .logging_util import init_logging, get_logger
from .application import PasarApplication

_log = get_logger('main')


def main(version):
    # Initialise logging/profiling subsystem (off by default;
    # set PASAR_LOG=1 and/or PASAR_PROFILE=1 to activate).
    init_logging()
    _log.info('Starting Pasar  version=%s  python=%s', version, sys.version.split()[0])

    app = PasarApplication(version=version)
    return app.run(sys.argv)
