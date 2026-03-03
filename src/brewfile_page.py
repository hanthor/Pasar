# brewfile_page.py - Page for displaying Brewfile contents
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib
from .backend import Package
from .package_tile import PasarPackageTile
from .logging_util import get_logger

_log = get_logger('brewfile_page')


@Gtk.Template(resource_path='/dev/jamesq/Pasar/brewfile-page.ui')
class PasarBrewfilePage(Adw.Bin):
    __gtype_name__ = 'PasarBrewfilePage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    brewfile_stack = Gtk.Template.Child()
    taps_section = Gtk.Template.Child()
    taps_list = Gtk.Template.Child()
    formulae_section = Gtk.Template.Child()
    formulae_flow = Gtk.Template.Child()
    casks_section = Gtk.Template.Child()
    casks_flow = Gtk.Template.Child()
    install_all_button = Gtk.Template.Child()
    remove_all_button = Gtk.Template.Child()

    def __init__(self, backend, task_manager, **kwargs):
        super().__init__(**kwargs)
        self.backend = backend
        self.task_manager = task_manager
        self.parsed_data = None
        self._packages = []
        self._taps_to_add = []
        
        # Connect button signals
        self.install_all_button.connect('clicked', self._on_install_all_clicked)
        self.remove_all_button.connect('clicked', self._on_remove_all_clicked)

    def load_brewfile(self, path):
        """Load and display a Brewfile."""
        _log.info('Loading Brewfile: %s', path)
        self.brewfile_stack.set_visible_child_name('loading')
        
        # Parse the brewfile
        self.parsed_data = self.backend.parse_brewfile(path)
        
        # Tap any taps that aren't already tapped
        self._process_taps()
        
        # Load packages in a thread to avoid blocking UI
        import threading
        thread = threading.Thread(target=self._load_packages_thread, daemon=True)
        thread.start()

    def _load_packages_thread(self):
        """Load packages in a background thread."""
        import time
        # Small delay to let taps process
        time.sleep(0.5)
        
        if not self.parsed_data:
            _log.warning('No parsed data available')
            return
        
        _log.info('Loading packages: %d formulae, %d casks', 
                 len(self.parsed_data.get('formulae', [])),
                 len(self.parsed_data.get('casks', [])))
        
        # Load formulae
        formulae_tiles = []
        if self.parsed_data.get('formulae'):
            for formula_name in self.parsed_data['formulae']:
                _log.debug('Loading formula: %s', formula_name)
                pkg = self._get_or_fetch_package(formula_name, 'formula')
                if pkg:
                    self._packages.append(pkg)
                    formulae_tiles.append(pkg)
                else:
                    _log.warning('Failed to load formula: %s', formula_name)
        
        # Load casks
        casks_tiles = []
        if self.parsed_data.get('casks'):
            for cask_name in self.parsed_data['casks']:
                _log.debug('Loading cask: %s', cask_name)
                pkg = self._get_or_fetch_package(cask_name, 'cask')
                if pkg:
                    self._packages.append(pkg)
                    casks_tiles.append(pkg)
                else:
                    _log.warning('Failed to load cask: %s', cask_name)
        
        # Update UI on main thread
        GLib.idle_add(self._populate_tiles, formulae_tiles, casks_tiles)

    def _populate_tiles(self, formulae, casks):
        """Populate tiles on the main thread."""
        if formulae:
            self.formulae_section.set_visible(True)
            for pkg in formulae:
                tile = PasarPackageTile(package=pkg)
                tile.connect('clicked', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                self._load_tile_icon(tile, pkg)
                self.formulae_flow.append(tile)
        
        if casks:
            self.casks_section.set_visible(True)
            for pkg in casks:
                tile = PasarPackageTile(package=pkg)
                tile.connect('clicked', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                self._load_tile_icon(tile, pkg)
                self.casks_flow.append(tile)
        
        _log.info('Finished populating %d packages', len(self._packages))
        self.brewfile_stack.set_visible_child_name('content')
        return False
        """Process taps from the Brewfile."""
        if not self.parsed_data or not self.parsed_data['taps']:
            return
            
        self.taps_section.set_visible(True)
        
        # Clear existing
        while child := self.taps_list.get_first_child():
            self.taps_list.remove(child)
        
        for tap in self.parsed_data['taps']:
            # Add tap to list
            row = Adw.ActionRow(title=tap)
            row.add_suffix(Gtk.Spinner())
            self.taps_list.append(row)
            
            # Tap it
            self._tap_async(tap, row)

    def _tap_async(self, tap, row):
        """Tap a repository."""
        _log.info('Tapping: %s', tap)
        
        def on_complete(success):
            spinner = row.get_last_child()
            if isinstance(spinner, Gtk.Spinner):
                row.remove(spinner)
            
            icon = Gtk.Image.new_from_icon_name(
                'emblem-ok-symbolic' if success else 'dialog-warning-symbolic'
            )
            row.add_suffix(icon)
            
        # Run brew tap command
        import subprocess
        def run_tap():
            try:
                result = subprocess.run(
                    ['brew', 'tap', tap],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                success = result.returncode == 0
                GLib.idle_add(lambda: on_complete(success))
            except Exception as e:
                _log.error('Failed to tap %s: %s', tap, e)
                GLib.idle_add(lambda: on_complete(False))
        
        import threading
        thread = threading.Thread(target=run_tap, daemon=True)
        thread.start()

    def _get_or_fetch_package(self, name, pkg_type):
        """Get package from backend or fetch info."""
        pkgs = self.backend.formulae if pkg_type == 'formula' else self.backend.casks
        
        # Try to find in loaded packages
        for p in pkgs:
            if p.name == name or p.full_name == name:
                _log.debug('Found %s in cache', name)
                return p
        
        # Not found - fetch info for this specific package
        _log.info('Package %s not in cache, fetching info', name)
        try:
            pkg_info = self.backend.get_package_info(name, pkg_type)
            
            if pkg_info:
                _log.debug('Successfully fetched info for %s', name)
                return Package(data=pkg_info, pkg_type=pkg_type, installed_set=self.backend.installed)
            else:
                _log.warning('No info returned for %s', name)
        except Exception as e:
            _log.error('Error fetching package info for %s: %s', name, e)
        
        # Create a minimal placeholder
        _log.info('Creating placeholder for %s', name)
        return Package(data={'name': name, 'desc': 'Package from Brewfile'}, 
                      pkg_type=pkg_type, installed_set=self.backend.installed)

    def _load_tile_icon(self, tile, package):
        """Load icon for a package tile."""
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self.backend.fetch_icon_async(package, on_icon_fetched)

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)

    def _on_install_all_clicked(self, button):
        """Install all packages from the Brewfile."""
        _log.info('Install-all from Brewfile: %d packages', len(self._packages))
        installed_count = 0
        for pkg in self._packages:
            if not pkg.installed:
                self.task_manager.install(pkg)
                installed_count += 1
        
        if installed_count > 0:
            _log.info('Queued %d packages for installation', installed_count)

    def _on_remove_all_clicked(self, button):
        """Remove all packages from the Brewfile."""
        _log.info('Remove-all from Brewfile: %d packages', len(self._packages))
        removed_count = 0
        for pkg in self._packages:
            if pkg.installed:
                self.task_manager.remove(pkg)
                removed_count += 1
        
        if removed_count > 0:
            _log.info('Queued %d packages for removal', removed_count)
