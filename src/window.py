# window.py - Main application window
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gio, GObject
from .backend import BrewBackend
from .task_manager import TaskManager
from .logging_util import get_logger

_log = get_logger('window')

# These imports register the GTypes BEFORE the window template is parsed.
# GTK needs to know about these custom widget types when building the UI.
from .browse_page import PasarBrowsePage      # noqa: F401
from .search_page import PasarSearchPage      # noqa: F401
from .installed_page import PasarInstalledPage  # noqa: F401
from .global_progress import PasarGlobalProgress # noqa: F401
from .brewfile_page import PasarBrewfilePage  # noqa: F401


@Gtk.Template(resource_path='/dev/jamesq/Pasar/window.ui')
class PasarWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'PasarWindow'

    toast_overlay = Gtk.Template.Child()
    browse_page = Gtk.Template.Child()
    search_page = Gtk.Template.Child()
    installed_page = Gtk.Template.Child()
    main_stack = Gtk.Template.Child()
    task_button = Gtk.Template.Child()
    global_progress = Gtk.Template.Child()
    navigation_view = Gtk.Template.Child()

    def __init__(self, package_to_open=None, **kwargs):
        super().__init__(**kwargs)
        _log.debug('PasarWindow.__init__')

        # Store deeplink target
        self._package_to_open = package_to_open
        self._formulae_loaded = False
        self._casks_loaded = False
        self._brewfile_page_count = 0  # Counter for unique brewfile tab names

        # Shared backend
        self.backend = BrewBackend()

        # Task manager (central operation coordinator)
        self.task_manager = TaskManager(self.backend)
        self.task_manager.connect('task-added', self._on_task_added)
        self.task_manager.connect('task-finished', self._on_task_finished)
        self.task_manager.connect('notify::active-count', self._on_active_count_changed)
        self.task_manager.connect('task-changed', self._on_task_progress_changed)

        # Task button in header bar
        self.task_button.connect('clicked', self._on_task_button_clicked)

        # Wire pages to backend
        self.browse_page.set_backend(self.backend)
        self.search_page.set_backend(self.backend)
        self.installed_page.set_backend(self.backend)

        # Wire package open signal from pages
        self.browse_page.connect('package-activated', self._on_package_activated)
        self.search_page.connect('package-activated', self._on_package_activated)
        self.installed_page.connect('package-activated', self._on_package_activated)

        # Wire package install signals from inline tile buttons
        self.browse_page.connect('install-requested', self._on_install_requested)
        self.search_page.connect('install-requested', self._on_install_requested)
        self.installed_page.connect('install-requested', self._on_install_requested)

        # Window actions
        refresh_action = Gio.SimpleAction.new('refresh', None)
        refresh_action.connect('activate', self._on_refresh)
        self.add_action(refresh_action)

        open_brewfile_action = Gio.SimpleAction.new('open-brewfile', None)
        open_brewfile_action.connect('activate', self._on_open_brewfile)
        self.add_action(open_brewfile_action)
        self.get_application().set_accels_for_action('win.open-brewfile', ['<Ctrl>o'])

        # Settings for size persistence
        self._settings = Gio.Settings.new('dev.jamesq.Pasar')
        self.set_default_size(
            self._settings.get_int('window-width'),
            self._settings.get_int('window-height'),
        )
        if self._settings.get_boolean('window-maximized'):
            self.maximize()

        self.connect('close-request', self._on_close)

        # Start loading
        self.backend.connect('formulae-loaded', self._on_formulae_loaded)
        self.backend.connect('casks-loaded', self._on_casks_loaded)
        self.backend.connect('installed-loaded', self._on_installed_loaded)
        self.backend.connect('notify::loading', self._on_backend_loading_changed)
        _log.info('Kicking off backend.load_all_async()')
        self.backend.load_all_async()

    def _find_package_by_name(self, package_name):
        target = (package_name or '').strip().lower()
        if not target:
            return None

        for pkg in self.backend.formulae:
            if pkg.name.lower() == target or (pkg.display_name and pkg.display_name.lower() == target):
                return pkg

        for pkg in self.backend.casks:
            if pkg.name.lower() == target or (pkg.display_name and pkg.display_name.lower() == target):
                return pkg

        return None

    def open_package_by_name(self, package_name, show_not_found=True):
        """Open a package details page by name (deeplink support)."""
        _log.info('Attempting to open package: %s', package_name)

        package = self._find_package_by_name(package_name)
        if package:
            _log.info('Found package: %s (%s)', package.name, package.pkg_type)
            self._on_package_activated(None, package)
            return True

        if show_not_found:
            _log.warning('Package not found: %s', package_name)
            self.toast_overlay.add_toast(Adw.Toast.new(f'Package "{package_name}" not found'))
        return False


    # ── Task manager signals ─────────────────────────────────────
    def _on_task_added(self, mgr, task):
        _log.info('Task added: %s', task.title)
        op_label = task.title
        self.toast_overlay.add_toast(Adw.Toast.new(f'{op_label}…'))

    def _on_task_finished(self, mgr, task):
        _log.info('Task finished: %s  status=%s', task.title, task.status)
        pkg = task.package
        from .task_manager import TaskStatus
        if task.status == TaskStatus.COMPLETED:
            verb = 'Installed' if task.operation == 'install' else (
                'Removed' if task.operation == 'uninstall' else 'Upgraded'
            )
            self.toast_overlay.add_toast(Adw.Toast.new(
                f'{verb}: {pkg.display_name or pkg.name}'
            ))
        elif task.status == TaskStatus.FAILED:
            self.toast_overlay.add_toast(Adw.Toast.new(
                f'Failed: {pkg.display_name or pkg.name}'
            ))
        # Refresh installed page
        self.installed_page.refresh(self.backend)

    def _on_active_count_changed(self, mgr, pspec):
        count = mgr.active_count
        if count > 0:
            self.task_button.set_tooltip_text(f'{count} task{"s" if count != 1 else ""} running')
            self.task_button.set_can_target(True)
            self.global_progress.props.active = True
        else:
            self.task_button.set_tooltip_text('Downloads & Tasks')
            self.task_button.set_can_target(False)
            self.global_progress.props.active = False
            self.global_progress.props.fraction = 0.0

    def _on_task_progress_changed(self, mgr, task):
        # Calculate overall progress of active tasks
        active_tasks = [t for t in mgr.tasks if t.is_active]
        if not active_tasks:
            self.global_progress.props.fraction = 0.0
            return
        
        total_progress = sum(t.progress for t in active_tasks)
        avg_progress = total_progress / len(active_tasks)
        self.global_progress.props.fraction = avg_progress

    def _on_task_button_clicked(self, button):
        from .task_panel import PasarTaskPanel
        panel = PasarTaskPanel(task_manager=self.task_manager)
        panel.present(self)

    # ── Package / data signals ───────────────────────────────────
    def _on_formulae_loaded(self, backend, packages):
        _log.info('Formulae loaded: %d packages', len(packages))
        self._formulae_loaded = True
        self.browse_page.populate_formulae(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)
        self._check_deeplink()

    def _on_casks_loaded(self, backend, packages):
        _log.info('Casks loaded: %d packages', len(packages))
        self._casks_loaded = True
        self.browse_page.populate_casks(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)
        self._check_deeplink()

    def _on_installed_loaded(self, backend, _):
        _log.debug('Installed-loaded signal received')

    def _on_backend_loading_changed(self, backend, _pspec):
        if backend.loading:
            return
        if self._package_to_open:
            self.open_package_by_name(self._package_to_open, show_not_found=True)
            self._package_to_open = None

    def _check_deeplink(self):
        """Check if we should open a package from deeplink after data loads."""
        if not self._package_to_open:
            return

        if self.open_package_by_name(self._package_to_open, show_not_found=False):
            self._package_to_open = None


    def _on_package_activated(self, page, package):
        _log.debug('Package activated: %s (%s)', package.name, package.pkg_type)
        from .package_details import PasarPackageDetails
        dialog = PasarPackageDetails(
            package=package,
            backend=self.backend,
            task_manager=self.task_manager,
        )
        dialog.connect('package-changed', self._on_package_changed)
        self.navigation_view.push(dialog)

    def _on_package_changed(self, dialog, package):
        # Refresh installed page when something is installed/removed
        self.installed_page.refresh(self.backend)

    def _on_install_requested(self, page, package):
        _log.info('Install requested from page: %s (%s)', package.name, package.pkg_type)
        self.task_manager.install(package)

    def _on_refresh(self, action, param):
        _log.info('Manual refresh triggered')
        self.browse_page.set_loading()
        self.backend.load_all_async()
        self.toast_overlay.add_toast(Adw.Toast.new('Refreshing package list…'))

    def _on_open_brewfile(self, action, param):
        _log.info('Open Brewfile action triggered')
        from gi.repository import Gtk
        
        # Create file filter for .Brewfile files
        filter_brewfile = Gtk.FileFilter()
        filter_brewfile.set_name('Brewfile')
        filter_brewfile.add_pattern('*.Brewfile')
        filter_brewfile.add_pattern('Brewfile')
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name('All files')
        filter_all.add_pattern('*')
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_brewfile)
        filters.append(filter_all)
        
        # Create and configure file dialog
        dialog = Gtk.FileDialog()
        dialog.set_title('Open Brewfile')
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_brewfile)
        
        # Suggest the ublue-os brewfile directory if it exists
        import os
        default_path = '/usr/share/ublue-os/homebrew'
        if os.path.exists(default_path):
            initial_folder = Gio.File.new_for_path(default_path)
            dialog.set_initial_folder(initial_folder)
        
        # Open dialog and handle response
        dialog.open(self, None, self._on_brewfile_selected)

    def _on_brewfile_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                _log.info('User selected Brewfile: %s', path)
                self.open_brewfile(path)
        except Exception as e:
            if 'dismissed' not in str(e).lower():
                _log.error('Error opening Brewfile: %s', e)
                self.toast_overlay.add_toast(Adw.Toast.new('Failed to open Brewfile'))

    def open_brewfile(self, path):
        """Open a Brewfile as a new tab in the main window."""
        import os
        
        # Extract filename for tab title
        filename = os.path.basename(path)
        # Remove .Brewfile extension
        if filename.endswith('.Brewfile'):
            title = filename[:-9]  # Remove '.Brewfile'
        elif filename == 'Brewfile':
            title = 'Brewfile'
        else:
            title = filename
        
        # Capitalize first letter
        title = title.capitalize()
        
        # Create brewfile page
        from .brewfile_page import PasarBrewfilePage
        brewfile_page = PasarBrewfilePage(
            backend=self.backend,
            task_manager=self.task_manager
        )
        
        # Connect signals
        brewfile_page.connect('package-activated', self._on_package_activated)
        brewfile_page.connect('install-requested', self._on_install_requested)
        
        # Add as a new tab with a unique name
        self._brewfile_page_count += 1
        page_name = f'brewfile_{self._brewfile_page_count}'
        
        # Add page to stack
        stack_page = self.main_stack.add_titled(
            brewfile_page,
            page_name,
            title
        )
        
        # Switch to the new tab
        self.main_stack.set_visible_child_name(page_name)
        
        # Load the brewfile
        brewfile_page.load_brewfile(path)
        
        _log.info('Added Brewfile tab: %s', title)

    def _on_close(self, *args):
        w, h = self.get_default_size()
        self._settings.set_int('window-width', w)
        self._settings.set_int('window-height', h)
        self._settings.set_boolean('window-maximized', self.is_maximized())
