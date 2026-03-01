# browse_page.py - Browse / discover page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import PasarPackageTile


# Well-known popular formulae to feature
POPULAR_FORMULAE = [
    'git', 'wget', 'curl', 'node', 'python@3.12', 'ffmpeg', 'htop',
    'vim', 'neovim', 'tmux', 'ripgrep', 'fzf', 'jq', 'bat', 'eza',
    'imagemagick', 'yt-dlp', 'gh', 'go', 'rust', 'php',
]

# Well-known popular casks to feature
POPULAR_CASKS = [
    'firefox', 'google-chrome', 'visual-studio-code', 'vlc', 'iterm2',
    'slack', 'zoom', 'spotify', 'discord', 'rectangle', 'obsidian',
    'warp', 'tableplus', 'postman', 'docker', 'alfred',
]


@Gtk.Template(resource_path='/dev/jamesq/Pasar/browse-page.ui')
class PasarBrowsePage(Adw.Bin):
    __gtype_name__ = 'PasarBrowsePage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    browse_stack = Gtk.Template.Child()
    popular_flow = Gtk.Template.Child()
    casks_flow = Gtk.Template.Child()
    recent_flow = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None

    def set_backend(self, backend):
        self._backend = backend

    def set_loading(self):
        self.browse_stack.set_visible_child_name('loading')

    def populate_formulae(self, packages):
        self._fill_flow(self.popular_flow, packages, POPULAR_FORMULAE)
        self._fill_recent(packages)
        self._maybe_show_content()

    def populate_casks(self, packages):
        self._fill_flow(self.casks_flow, packages, POPULAR_CASKS)
        self._maybe_show_content()

    def _fill_flow(self, flowbox, packages, preferred_names):
        # Clear existing
        while child := flowbox.get_first_child():
            flowbox.remove(child)

        # Build name->pkg map
        name_map = {p.name: p for p in packages}

        shown = []
        # First add preferred names in order
        for name in preferred_names:
            if name in name_map:
                shown.append(name_map[name])

        # Fill remaining slots from package list (sorted by name length as lightweight
        # popularity proxy - shorter names tend to be well-known)
        remaining = [p for p in packages if p.name not in {s.name for s in shown}]
        remaining.sort(key=lambda p: len(p.name))
        shown.extend(remaining[: 24 - len(shown)])

        for pkg in shown:
            tile = PasarPackageTile(package=pkg)
            tile.connect('clicked', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            flowbox.append(tile)

    def _fill_recent(self, packages):
        while child := self.recent_flow.get_first_child():
            self.recent_flow.remove(child)
        # Show last 12 packages in the list (API returns them in various orders,
        # so "recent" here is a rough approximation)
        for pkg in packages[-12:]:
            tile = PasarPackageTile(package=pkg)
            tile.connect('clicked', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            self.recent_flow.append(tile)

    def _maybe_show_content(self):
        # Show content only when at least one section has tiles
        if self.popular_flow.get_first_child() or self.casks_flow.get_first_child():
            self.browse_stack.set_visible_child_name('content')

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)
