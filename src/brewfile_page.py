# brewfile_page.py - Page for displaying Brewfile contents
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from .backend import Package
from .package_tile import PasarPackageTile
from .logging_util import get_logger, log_timing

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
    taps_flow = Gtk.Template.Child()
    formulae_section = Gtk.Template.Child()
    formulae_flow = Gtk.Template.Child()
    casks_section = Gtk.Template.Child()
    casks_flow = Gtk.Template.Child()
    flatpaks_section = Gtk.Template.Child()
    flatpaks_flow = Gtk.Template.Child()
    install_all_button = Gtk.Template.Child()
    remove_all_button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.backend = None
        self.task_manager = None
        self.parsed_data = None
        self._packages = []
        self._taps_to_add = []
        self._tap_errors = {}
        self._tile_map = {}  # Maps package name -> (tile, package) for lazy icon loading
        self._tap_lock = threading.Lock()
        self._pending_taps = 0
        self._taps_done_event = threading.Event()
        self._taps_done_event.set()
        
        # Connect button signals
        self.install_all_button.connect('clicked', self._on_install_all_clicked)
        self.remove_all_button.connect('clicked', self._on_remove_all_clicked)

    def set_backend_and_manager(self, backend, task_manager):
        """Set the backend and task manager after widget creation."""  
        self.backend = backend
        self.task_manager = task_manager

    def load_brewfile(self, path):
        """Load and display a Brewfile with overall timing."""
        _log.info('=' * 70)
        _log.info('Loading Brewfile: %s', path)
        _log.info('=' * 70)
        
        overall_start = time.perf_counter()
        self.brewfile_stack.set_visible_child_name('loading')
        self._tap_errors = {}
        
        # Parse the brewfile
        self.parsed_data = self.backend.parse_brewfile(path)
        
        # Tap any taps that aren't already tapped
        self._process_taps()
        
        # Load packages in a thread to avoid blocking UI
        import threading
        
        def load_and_log():
            self._load_packages_thread()
            overall_elapsed = (time.perf_counter() - overall_start) * 1000
            _log.info('=' * 70)
            _log.info('TOTAL BREWFILE LOAD TIME: %.1f ms', overall_elapsed)
            _log.info('=' * 70)
        
        thread = threading.Thread(target=load_and_log, daemon=True)
        thread.start()

    def _process_taps(self):
        """Process taps from the Brewfile."""
        if not self.parsed_data or not self.parsed_data.get('taps'):
            self._taps_done_event.set()
            return
            
        self.taps_section.set_visible(True)
        
        # Clear existing
        while child := self.taps_flow.get_first_child():
            self.taps_flow.remove(child)

        taps = self.parsed_data.get('taps', [])
        with self._tap_lock:
            self._pending_taps = len(taps)
            if self._pending_taps > 0:
                self._taps_done_event.clear()
            else:
                self._taps_done_event.set()
        
        for tap in taps:
            # Create a compact pill-style box
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.add_css_class('pill')
            box.set_margin_start(4)
            box.set_margin_end(4)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            
            # Add tap label
            label = Gtk.Label(label=tap)
            box.append(label)

            # Add click handler for failed taps
            click_gesture = Gtk.GestureClick.new()
            click_gesture.connect('released', lambda _g, _n, _x, _y, tap_name=tap: self._on_tap_clicked(tap_name))
            box.add_controller(click_gesture)
            
            # Add spinner
            spinner = Gtk.Spinner()
            spinner.start()
            box.append(spinner)
            
            self.taps_flow.append(box)
            
            # Tap it
            self._tap_async(tap, box, spinner, label)

    def _tap_async(self, tap, box, spinner, label):
        """Tap a repository with profiling and detailed error reporting."""
        _log.info('Tapping: %s', tap)
        tap_start = time.perf_counter()
        error_message = None
        
        def on_complete(success, elapsed_ms, error_msg=None):
            # Remove the spinner
            try:
                box.remove(spinner)
            except Exception as e:
                _log.warning('Failed to remove spinner for tap %s: %s', tap, e)
            
            # Add status icon with tooltip on failure
            icon = Gtk.Image.new_from_icon_name(
                'emblem-ok-symbolic' if success else 'dialog-warning-symbolic'
            )
            if not success and error_msg:
                self._tap_errors[tap] = error_msg
                icon.set_tooltip_text(error_msg)
                box.set_tooltip_text(error_msg)
                box.add_css_class('error')
            else:
                self._tap_errors.pop(tap, None)
                box.set_tooltip_text(None)
                box.add_css_class('success')
            box.append(icon)
            
            status = 'success' if success else 'failed'
            log_msg = f'Tap {tap}: {status} ({elapsed_ms:.1f} ms)'
            if error_msg:
                log_msg += f' - {error_msg}'
                _log.warning(log_msg)
            else:
                _log.info(log_msg)

            with self._tap_lock:
                self._pending_taps = max(0, self._pending_taps - 1)
                if self._pending_taps == 0:
                    self._taps_done_event.set()
                    _log.info('Tap phase complete')
            
        # Run brew tap command
        def run_tap():
            nonlocal error_message
            try:
                result = subprocess.run(
                    ['brew', 'tap', tap],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                success = result.returncode == 0
                elapsed_ms = (time.perf_counter() - tap_start) * 1000
                if not success:
                    error_message = result.stderr.strip() if result.stderr else 'Unknown error'
                    _log.error('Tap %s failed: %s', tap, error_message)
                GLib.idle_add(lambda: on_complete(success, elapsed_ms, error_message))
            except subprocess.TimeoutExpired:
                error_message = 'Timeout (30 seconds)'
                _log.error('Tap %s timed out', tap)
                elapsed_ms = (time.perf_counter() - tap_start) * 1000
                GLib.idle_add(lambda: on_complete(False, elapsed_ms, error_message))
            except Exception as e:
                error_message = str(e)
                _log.error('Failed to tap %s: %s', tap, error_message)
                elapsed_ms = (time.perf_counter() - tap_start) * 1000
                GLib.idle_add(lambda: on_complete(False, elapsed_ms, error_message))
        
        import threading
        thread = threading.Thread(target=run_tap, daemon=True)
        thread.start()

    def _on_tap_clicked(self, tap):
        """Show detailed modal error for failed taps when clicked."""
        error_message = self._tap_errors.get(tap)
        if not error_message:
            return

        root = self.get_root()
        if not root:
            return

        dialog = Adw.MessageDialog(
            transient_for=root,
            heading=f'Tap failed: {tap}',
            body=error_message,
        )
        dialog.add_response('ok', 'OK')
        dialog.set_default_response('ok')
        dialog.set_close_response('ok')
        dialog.present()

    def _load_packages_thread(self):
        """Load packages with lazy loading: show names immediately, fetch details async."""
        import time
        thread_start = time.perf_counter()
        
        try:
            if not self.parsed_data:
                _log.warning('No parsed data available')
                GLib.idle_add(self._populate_tiles, [], [], [])
                return
            
            # PHASE 1: Create placeholder packages with just names - INSTANT display
            formulae_placeholders = []
            casks_placeholders = []
            flatpak_placeholders = []
            
            # Sort alphabetically for better UX
            sorted_formulae = sorted(self.parsed_data.get('formulae', []))
            sorted_casks = sorted(self.parsed_data.get('casks', []))
            sorted_flatpaks = sorted(self.parsed_data.get('flatpaks', []))
            
            _log.info('Creating placeholders: %d formulae, %d casks, %d flatpaks', 
                     len(sorted_formulae), len(sorted_casks), len(sorted_flatpaks))
            
            # Create minimal placeholder packages
            for formula_name in sorted_formulae:
                pkg = Package(data={'name': formula_name, 'desc': ''}, pkg_type='formula')
                formulae_placeholders.append(pkg)
                self._packages.append(pkg)
            
            for cask_name in sorted_casks:
                pkg = Package(data={'name': cask_name, 'desc': ''}, pkg_type='cask')
                casks_placeholders.append(pkg)
                self._packages.append(pkg)
            
            for app_id in sorted_flatpaks:
                pkg = Package(data={'id': app_id, 'name': app_id, 'summary': ''}, pkg_type='flatpak')
                flatpak_placeholders.append(pkg)
                self._packages.append(pkg)
            
            placeholder_time = (time.perf_counter() - thread_start) * 1000
            _log.info('Placeholders created in %.1f ms - displaying UI now', placeholder_time)
            
            # PHASE 2: Show UI immediately with placeholders
            GLib.idle_add(self._populate_tiles, formulae_placeholders, casks_placeholders, flatpak_placeholders)
            
            # PHASE 3: Fetch metadata and icons asynchronously in background
            _log.info('Starting lazy metadata and icon loading')
            self._lazy_load_metadata(
                sorted_formulae, formulae_placeholders, 'formula',
                sorted_casks, casks_placeholders, 'cask',
                sorted_flatpaks, flatpak_placeholders, 'flatpak'
            )
            
            total_time = (time.perf_counter() - thread_start) * 1000
            _log.info('UI displayed + background loading started in %.1f ms', total_time)
            
        except Exception as e:
            _log.error('FATAL ERROR in _load_packages_thread: %s', e, exc_info=True)
            GLib.idle_add(self._populate_tiles, [], [], [])
    
    def _lazy_load_metadata(self, formulae_names, formulae_pkgs, formula_type,
                            casks_names, casks_pkgs, cask_type,
                            flatpaks_names, flatpaks_pkgs, flatpak_type):
        """Lazy load metadata with strict phase order and parallel workers per phase."""
        import time
        
        def load_metadata_for_package(name, pkg, pkg_type):
            """Fetch full metadata and update the package object."""
            try:
                start = time.perf_counter()
                
                if pkg_type == 'flatpak':
                    full_pkg = self._get_or_fetch_flatpak(name)
                else:
                    full_pkg = self._get_or_fetch_package(name, pkg_type)
                
                if full_pkg:
                    # Update the placeholder package with full data
                    pkg.set_property('description', full_pkg.description)
                    pkg.set_property('homepage', full_pkg.homepage)
                    pkg.set_property('version', full_pkg.version)
                    pkg.set_property('display_name', full_pkg.display_name)
                    if hasattr(full_pkg, 'icon_url'):
                        pkg.set_property('icon_url', full_pkg.icon_url)
                    
                    elapsed = (time.perf_counter() - start) * 1000
                    _log.debug('Lazy loaded %s (%s): %.1f ms', name, pkg_type, elapsed)
                    
                    # NOW load the icon for this package
                    if name in self._tile_map:
                        tile, _ = self._tile_map[name]
                        GLib.idle_add(self._load_tile_icon, tile, pkg)
                    
                    return True
                else:
                    _log.warning('Failed to lazy load %s', name)
                    return False
            except Exception as e:
                _log.error('Error lazy loading %s: %s', name, e)
                return False
        
        formula_items = [(name, pkg, 'formula') for name, pkg in zip(formulae_names, formulae_pkgs)]
        cask_items = [(name, pkg, 'cask') for name, pkg in zip(casks_names, casks_pkgs)]
        flatpak_items = [(app_id, pkg, 'flatpak') for app_id, pkg in zip(flatpaks_names, flatpaks_pkgs)]

        all_total = len(formula_items) + len(cask_items) + len(flatpak_items)
        _log.info('Waiting for taps phase before metadata loading')
        taps_done = self._taps_done_event.wait(timeout=180)
        if not taps_done:
            _log.warning('Tap phase wait timed out; continuing with package metadata loading')
        else:
            _log.info('Starting package metadata phases: formula -> cask -> flatpak')

        loaded = 0
        failed = 0

        def run_phase(phase_name, items):
            nonlocal loaded, failed
            if not items:
                _log.info('Phase %s: no items', phase_name)
                return

            _log.info('Phase %s: starting %d items with 10 workers', phase_name, len(items))
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_item = {
                    executor.submit(load_metadata_for_package, name, pkg, pkg_type): (name, pkg_type)
                    for name, pkg, pkg_type in items
                }

                phase_done = 0
                phase_loaded = 0
                phase_failed = 0
                for future in as_completed(future_to_item):
                    name, _ = future_to_item[future]
                    try:
                        success = future.result()
                        if success:
                            loaded += 1
                            phase_loaded += 1
                        else:
                            failed += 1
                            phase_failed += 1
                    except Exception as e:
                        failed += 1
                        phase_failed += 1
                        _log.error('Exception loading %s in phase %s: %s', name, phase_name, e)

                    phase_done += 1
                    total_done = loaded + failed
                    if total_done % 10 == 0 or phase_done == len(items):
                        _log.info(
                            'Lazy load progress: %d/%d complete (%d succeeded, %d failed)',
                            total_done,
                            all_total,
                            loaded,
                            failed,
                        )

            _log.info(
                'Phase %s complete: %d/%d succeeded, %d failed',
                phase_name,
                phase_loaded,
                len(items),
                phase_failed,
            )

        run_phase('formula', formula_items)
        run_phase('cask', cask_items)
        run_phase('flatpak', flatpak_items)

        _log.info(
            'Ordered lazy loading complete: %d loaded, %d failed out of %d total',
            loaded,
            failed,
            all_total,
        )

    def _populate_tiles(self, formulae, casks, flatpaks):
        """Populate tiles on the main thread - icons loaded lazily later."""
        # Store tile references for lazy icon loading
        self._tile_map = {}
        
        if formulae:
            self.formulae_section.set_visible(True)
            for pkg in formulae:
                tile = PasarPackageTile(package=pkg)
                tile.connect('clicked', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet - will be done after metadata fetches
                self._tile_map[pkg.name] = (tile, pkg)
                self.formulae_flow.append(tile)
        
        if casks:
            self.casks_section.set_visible(True)
            for pkg in casks:
                tile = PasarPackageTile(package=pkg)
                tile.connect('clicked', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet
                self._tile_map[pkg.name] = (tile, pkg)
                self.casks_flow.append(tile)

        if flatpaks:
            self.flatpaks_section.set_visible(True)
            for pkg in flatpaks:
                tile = PasarPackageTile(package=pkg)
                tile.connect('clicked', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet
                self._tile_map[pkg.name] = (tile, pkg)
                self.flatpaks_flow.append(tile)
        
        _log.info('Finished populating %d tiles (icons loading in background)', len(self._packages))
        self.brewfile_stack.set_visible_child_name('content')
        return False

    def _get_or_fetch_flatpak(self, app_id):
        """Fetch flatpak metadata from Flathub appstream with graceful fallback."""
        _log.info('Fetching flatpak metadata for %s', app_id)
        try:
            appstream = self.backend.get_flatpak_info(app_id)
            if appstream:
                _log.debug('Successfully fetched flatpak metadata for %s', app_id)
                return Package(data=appstream, pkg_type='flatpak')
            else:
                _log.warning('Flathub API returned empty result for flatpak %s (may not exist)', app_id)
        except Exception as e:
            _log.warning('Failed to fetch flatpak metadata for %s: %s (using fallback)', app_id, e)

        # Create package with Flathub fallback info
        _log.info('Creating fallback package for flatpak %s with Flathub link', app_id)
        return Package(
            data={
                'id': app_id,
                'name': app_id,
                'summary': 'Flatpak application from Brewfile',
                'urls': {'homepage': f'https://flathub.org/apps/{app_id}'},
            },
            pkg_type='flatpak',
        )

    def _get_or_fetch_package(self, name, pkg_type):
        """Get package from backend or fetch info with graceful fallback."""
        pkgs = self.backend.formulae if pkg_type == 'formula' else self.backend.casks
        
        # Try to find in loaded packages
        for p in pkgs:
            if p.name == name or p.full_name == name:
                _log.debug('Found %s in cache', name)
                return p
        
        # Not found - fetch info for this specific package
        _log.info('Package %s not in cache, fetching details', name)
        installed_set = self.backend._installed_formulae if pkg_type == 'formula' else self.backend._installed_casks
        try:
            pkg_info = self.backend.get_package_info(name, pkg_type)
            
            if pkg_info:
                _log.info('Successfully fetched info for %s', name)
                return Package(data=pkg_info, pkg_type=pkg_type, installed_set=installed_set)
            else:
                _log.warning('Package %s returned no info (may not exist or be from unfetched tap)', name)
        except Exception as e:
            _log.error('Error fetching package info for %s: %s', name, e)
        
        # Create a graceful fallback package with helpful information
        _log.info('Creating fallback package for %s (from Brewfile)', name)
        fallback_data = {
            'name': name,
            'desc': 'Package from Brewfile (details not available)',
            'homepage': f'https://brew.sh',  # Generic Homebrew link
        }
        return Package(data=fallback_data, 
                      pkg_type=pkg_type, installed_set=installed_set)

    def _load_tile_icon(self, tile, package):
        """Load icon for a package tile with profiling."""
        icon_start = time.perf_counter()
        
        def on_icon_fetched(pkg, pixbuf):
            elapsed_ms = (time.perf_counter() - icon_start) * 1000
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
                _log.debug('Icon loaded for %s: %.1f ms', pkg.name, elapsed_ms)
            else:
                _log.debug('No icon found for %s: %.1f ms', pkg.name, elapsed_ms)
        
        self.backend.fetch_icon_async(package, on_icon_fetched)

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            if pkg.pkg_type == 'flatpak':
                self._open_flatpak_in_bazaar(pkg)
                return
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
            if pkg.pkg_type == 'flatpak':
                continue
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
            if pkg.pkg_type == 'flatpak':
                continue
            if pkg.installed:
                self.task_manager.remove(pkg)
                removed_count += 1
        
        if removed_count > 0:
            _log.info('Queued %d packages for removal', removed_count)

    def _open_flatpak_in_bazaar(self, package):
        """Open a flatpak app id using appstream URI so MIME/xdg routing can launch Bazaar."""
        app_id = package.name
        uri = f'appstream://{app_id}'
        try:
            subprocess.Popen(['xdg-open', uri])
            _log.info('Opened flatpak in Bazaar via URI: %s', uri)
        except Exception as e:
            _log.error('Failed to open flatpak URI %s: %s', uri, e)
