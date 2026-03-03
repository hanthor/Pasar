# application.py - GtkApplication subclass
# SPDX-License-Identifier: GPL-3.0-or-later

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio, GLib, Gtk
from .window import PasarWindow
from .logging_util import get_logger

_log = get_logger('application')


class PasarApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version='0.1.0', **kwargs):
        super().__init__(
            application_id='dev.jamesq.Pasar',
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE | Gio.ApplicationFlags.DEFAULT_FLAGS,
            **kwargs,
        )
        self.version = version
        self._package_to_open = None
        self._brewfile_to_open = None
        
        # Add command-line options
        self.add_main_option(
            'package',
            ord('p'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            'Open a specific package by name',
            'PACKAGE',
        )
        self.add_main_option(
            'brewfile',
            ord('b'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.FILENAME,
            'Open a Brewfile',
            'FILE',
        )
        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])
        self.create_action('about', self._on_about_action)
        _log.debug('PasarApplication created  version=%s', version)

    def do_command_line(self, command_line):
        """Handle command-line arguments."""
        args = command_line.get_arguments()[1:]  # Skip argv[0]
        package_name = None
        brewfile_path = None

        index = 0
        while index < len(args):
            arg = args[index]
            if arg in ('--package', '-p') and index + 1 < len(args):
                package_name = args[index + 1]
                index += 2
                continue
            if arg.startswith('--package='):
                package_name = arg.split('=', 1)[1]
                index += 1
                continue
            if arg in ('--brewfile', '-b') and index + 1 < len(args):
                brewfile_path = args[index + 1]
                index += 2
                continue
            if arg.startswith('--brewfile='):
                brewfile_path = arg.split('=', 1)[1]
                index += 1
                continue
            if not arg.startswith('-') and package_name is None:
                package_name = arg
            index += 1

        if package_name:
            _log.info('Opening package from command-line: %s', package_name)
            self._package_to_open = package_name

        if brewfile_path:
            _log.info('Opening Brewfile from command-line: %s', brewfile_path)
            self._brewfile_to_open = brewfile_path

        if '--gapplication-service' not in args:
            self.activate()
            
        return 0


    def do_activate(self):
        _log.info('do_activate called')
        win = self.props.active_window
        if not win:
            _log.debug('Creating new PasarWindow')
            win = PasarWindow(application=self, package_to_open=self._package_to_open)
            self._package_to_open = None
        elif self._package_to_open:
            # Window exists, just open the package
            win.open_package_by_name(self._package_to_open)
            self._package_to_open = None

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_resource('/dev/jamesq/Pasar/style.css')
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        win.present()

        # Open brewfile if requested
        if self._brewfile_to_open:
            self._open_brewfile_dialog(win, self._brewfile_to_open)
            self._brewfile_to_open = None

    def do_open(self, files, n_files, hint):
        _log.info('do_open called  n_files=%d  hint=%r', n_files, hint)
        self.do_activate()
        win = self.props.active_window
        for gfile in files:
            path = gfile.get_path()
            if path and path.endswith('.Brewfile'):
                _log.info('Opening Brewfile: %s', path)
                win.open_brewfile(path)

    def _open_brewfile_dialog(self, window, path):
        """Open a Brewfile."""
        window.open_brewfile(path)

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
