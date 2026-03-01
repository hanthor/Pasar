# package_tile.py - Package tile widget
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import Package


@Gtk.Template(resource_path='/dev/jamesq/Pasar/package-tile.ui')
class PasarPackageTile(Gtk.Box):
    __gtype_name__ = 'PasarPackageTile'
    
    __gsignals__ = {
        'clicked': (GObject.SignalFlags.RUN_LAST, None, ()),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    package_icon = Gtk.Template.Child()
    name_label = Gtk.Template.Child()
    desc_label = Gtk.Template.Child()
    type_badge = Gtk.Template.Child()
    installed_row = Gtk.Template.Child()
    install_button = Gtk.Template.Child()

    def __init__(self, package=None, **kwargs):
        super().__init__(**kwargs)
        self._package = None
        
        # Click gesture for the whole tile
        self._gesture = Gtk.GestureClick.new()
        self._gesture.connect('released', self._on_gesture_released)
        self.add_controller(self._gesture)
        
        self.install_button.connect('clicked', self._on_install_clicked)
        
        if package:
            self.set_package(package)

    def set_package(self, package):
        self._package = package
        self.name_label.set_label(package.display_name or package.name)
        self.desc_label.set_label(package.description or '')
        self.type_badge.set_label('cask' if package.pkg_type == 'cask' else 'formula')
        if package.pkg_type == 'cask':
            self.type_badge.add_css_class('cask-badge')
        else:
            self.type_badge.remove_css_class('cask-badge')
            
        is_installed = package.installed
        self.installed_row.set_visible(is_installed)
        self.install_button.set_visible(not is_installed)
        
        # Connect to installed changes
        package.connect('notify::installed', self._on_installed_changed)

    def get_package(self):
        return self._package

    def _on_installed_changed(self, pkg, pspec):
        is_installed = pkg.installed
        self.installed_row.set_visible(is_installed)
        self.install_button.set_visible(not is_installed)

    def _on_install_clicked(self, button):
        self.emit('install-requested')

    def _on_gesture_released(self, gesture, n_press, x, y):
        # In GTK4, if the child button handled the click, it won't reach here 
        # normally if we use BUBBLE phase. But to be safe, we can check if 
        # the click was over the install button.
        # However, a simpler way is to just emit 'clicked' and let the page handle it.
        # If the user clicked the actual install button, that button's handler 
        # will run first.
        self.emit('clicked')
