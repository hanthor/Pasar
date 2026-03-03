# installed_page.py - Installed packages page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import PasarPackageTile
from .logging_util import get_logger

_log = get_logger('installed_page')


@Gtk.Template(resource_path='/dev/jamesq/Pasar/installed-page.ui')
class PasarInstalledPage(Adw.Bin):
    __gtype_name__ = 'PasarInstalledPage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    installed_stack = Gtk.Template.Child()
    installed_flow = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None

    def set_backend(self, backend):
        self._backend = backend
        backend.connect('formulae-loaded', self._on_packages_loaded)
        backend.connect('casks-loaded', self._on_packages_loaded)

    def _on_packages_loaded(self, backend, packages):
        self.refresh(backend)

    def refresh(self, backend=None):
        if backend:
            self._backend = backend
        if not self._backend:
            return

        installed = self._backend.get_installed_packages()
        _log.debug('Refreshing installed page: %d packages', len(installed))

        # Clear flow
        while child := self.installed_flow.get_first_child():
            self.installed_flow.remove(child)

        if not installed:
            self.installed_stack.set_visible_child_name('empty')
            return

        for pkg in installed:
            tile = PasarPackageTile(package=pkg)
            tile.connect('clicked', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            self.installed_flow.append(tile)

        self.installed_stack.set_visible_child_name('content')

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)
