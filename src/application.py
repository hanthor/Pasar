# application.py - GtkApplication subclass
# SPDX-License-Identifier: GPL-3.0-or-later

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio, GLib, Gtk
from .window import PasarWindow


class PasarApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version='0.1.0', **kwargs):
        super().__init__(
            application_id='dev.jamesq.Pasar',
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.DEFAULT_FLAGS,
            **kwargs,
        )
        self.version = version
        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])
        self.create_action('about', self._on_about_action)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = PasarWindow(application=self)

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_resource('/dev/jamesq/Pasar/style.css')
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        win.present()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        win = self.props.active_window
        for gfile in files:
            path = gfile.get_path()
            if path and path.endswith('.Brewfile'):
                from .brewfile_dialog import PasarBrewfileDialog
                dialog = PasarBrewfileDialog(window=win)
                dialog.load_brewfile(path)
                dialog.present()

    def _on_about_action(self, *args):
        about = Adw.AboutDialog(
            application_name='Pasar',
            application_icon='dev.jamesq.Pasar',
            developer_name='James',
            version=self.version,
            developers=['James'],
            copyright='© 2026 James',
            license_type=Gtk.License.GPL_3_0,
            website='https://github.com/hanthor/pasar',
            issue_url='https://github.com/hanthor/pasar/issues',
            comments='A Homebrew App Store for GNOME',
        )
        about.present(self.props.active_window)

    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect('activate', callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f'app.{name}', shortcuts)
