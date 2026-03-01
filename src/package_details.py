# package_details.py - Package info + install/remove dialog
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gio, GObject, Pango
from .backend import Package, BrewBackend
from .task_manager import Task, TaskStatus, TaskOperation


@Gtk.Template(resource_path='/dev/jamesq/Pasar/package-details.ui')
class PasarPackageDetails(Adw.NavigationPage):
    __gtype_name__ = 'PasarPackageDetails'

    __gsignals__ = {
        'package-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    details_stack = Gtk.Template.Child()
    detail_icon = Gtk.Template.Child()
    detail_name = Gtk.Template.Child()
    detail_display_name = Gtk.Template.Child()
    detail_type_badge = Gtk.Template.Child()
    detail_desc = Gtk.Template.Child()
    install_button = Gtk.Template.Child()
    remove_button = Gtk.Template.Child()
    version_row = Gtk.Template.Child()
    license_row = Gtk.Template.Child()
    homepage_row = Gtk.Template.Child()
    type_row = Gtk.Template.Child()
    error_label = Gtk.Template.Child()
    detail_progress_bar = Gtk.Template.Child()
    screenshot_bin = Gtk.Template.Child()
    screenshot_picture = Gtk.Template.Child()

    def __init__(self, package=None, backend=None, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._package = package
        self._backend = backend
        self._task_manager = task_manager
        self._task = None

        self.install_button.connect('clicked', self._on_install_clicked)
        self.remove_button.connect('clicked', self._on_remove_clicked)
        self.homepage_row.connect('activated', self._on_homepage_activated)

        if package:
            self._populate(package)

    def _populate(self, package):
        self.set_title(package.display_name or package.name)
        self.detail_name.set_label(package.name)
        self.detail_desc.set_label(package.description or 'No description available.')

        if package.display_name and package.display_name != package.name:
            self.detail_display_name.set_label(package.display_name)
            self.detail_display_name.set_visible(True)

        self.detail_type_badge.set_label(package.pkg_type)
        if package.pkg_type == 'cask':
            self.detail_type_badge.add_css_class('cask-badge')

        self.version_row.set_subtitle(package.version or 'Unknown')
        self.type_row.set_subtitle(
            'Cask (GUI App / Binary)' if package.pkg_type == 'cask'
            else 'Formula (CLI / Library)'
        )

        if package.license_:
            self.license_row.set_subtitle(package.license_)
            self.license_row.set_visible(True)

        if package.homepage:
            self.homepage_row.set_subtitle(package.homepage)
        else:
            self.homepage_row.set_sensitive(False)
            self.homepage_row.set_subtitle('Not available')

        self._update_buttons()
        self.details_stack.set_visible_child_name('content')

        # Re-attach to any already-running task for this package
        if self._task_manager:
            existing = self._task_manager.get_task_for_package(package)
            if existing:
                self._bind_task(existing)

        # Fetch icon and screenshot
        if self._backend:
            self._backend.fetch_icon_async(package, self._on_icon_fetched)
            self._backend.fetch_screenshot_async(package, self._on_screenshot_fetched)

    def _update_buttons(self):
        pkg = self._package
        busy = self._task is not None and self._task.is_active
        if pkg.installed:
            self.install_button.set_visible(False)
            self.remove_button.set_visible(True)
            self.remove_button.set_sensitive(not busy)
        else:
            self.install_button.set_visible(True)
            self.remove_button.set_visible(False)
            self.install_button.set_sensitive(not busy)

    def _on_icon_fetched(self, package, pixbuf):
        if pixbuf and package == self._package:
            try:
                from gi.repository import Gdk
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.detail_icon.set_paintable(texture)
            except Exception:
                pass

    def _on_screenshot_fetched(self, package, pixbuf):
        if pixbuf and package == self._package:
            try:
                from gi.repository import Gdk
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.screenshot_picture.set_paintable(texture)
                self.screenshot_bin.set_visible(True)
            except Exception:
                pass

    # ── Task binding ─────────────────────────────────────────────
    def _bind_task(self, task):
        """Bind a Task — disable button + show slim progress bar; global bar handles overall feedback."""
        self._task = task
        self._update_buttons()
        self.detail_progress_bar.set_fraction(0.05)
        self.detail_progress_bar.set_visible(True)
        task.connect('notify::progress', self._on_task_progress)
        task.connect('finished', self._on_task_finished)

    def _on_task_progress(self, task, pspec):
        self.detail_progress_bar.set_fraction(task.progress)

    def _on_task_finished(self, task, success):
        self._task = None
        self.detail_progress_bar.set_fraction(1.0 if success else 0.0)
        self.detail_progress_bar.set_visible(False)
        self._update_buttons()
        if not success and task.error_detail:
            self.error_label.set_label(task.error_detail)
            self.error_label.set_visible(True)
        else:
            self.error_label.set_visible(False)
        self.emit('package-changed', self._package)

    # ── Button handlers ──────────────────────────────────────────
    def _on_install_clicked(self, button):
        if not self._task_manager:
            return
        task = self._task_manager.install(self._package)
        self._bind_task(task)

    def _on_remove_clicked(self, button):
        if not self._task_manager:
            return
        task = self._task_manager.remove(self._package)
        self._bind_task(task)

    def _on_homepage_activated(self, row):
        if self._package and self._package.homepage:
            launcher = Gtk.UriLauncher.new(self._package.homepage)
            launcher.launch(self.get_root(), None, None, None)
