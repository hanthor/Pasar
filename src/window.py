# window.py - Main application window
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gio, GObject
from .backend import BrewBackend
from .task_manager import TaskManager

# These imports register the GTypes BEFORE the window template is parsed.
# GTK needs to know about these custom widget types when building the UI.
from .browse_page import PasarBrowsePage      # noqa: F401
from .search_page import PasarSearchPage      # noqa: F401
from .installed_page import PasarInstalledPage  # noqa: F401
from .global_progress import PasarGlobalProgress # noqa: F401


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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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
        self.backend.load_all_async()

    # ── Task manager signals ─────────────────────────────────────
    def _on_task_added(self, mgr, task):
        op_label = task.title
        self.toast_overlay.add_toast(Adw.Toast.new(f'{op_label}…'))

    def _on_task_finished(self, mgr, task):
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
        self.browse_page.populate_formulae(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)

    def _on_casks_loaded(self, backend, packages):
        self.browse_page.populate_casks(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)

    def _on_installed_loaded(self, backend, _):
        pass

    def _on_package_activated(self, page, package):
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
        self.task_manager.install(package)

    def _on_refresh(self, action, param):
        self.browse_page.set_loading()
        self.backend.load_all_async()
        self.toast_overlay.add_toast(Adw.Toast.new('Refreshing package list…'))

    def _on_close(self, *args):
        w, h = self.get_default_size()
        self._settings.set_int('window-width', w)
        self._settings.set_int('window-height', h)
        self._settings.set_boolean('window-maximized', self.is_maximized())
