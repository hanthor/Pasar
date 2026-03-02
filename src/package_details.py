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
    readme_bin = Gtk.Template.Child()
    readme_view = Gtk.Template.Child()

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

        # Fetch icon, screenshot, and README
        if self._backend:
            self._backend.fetch_icon_async(package, self._on_icon_fetched)
            self._backend.fetch_screenshot_async(package, self._on_screenshot_fetched)
            self._backend.fetch_readme_async(package, self._on_readme_fetched)

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

    def _on_readme_fetched(self, package, text):
        if not text or package != self._package:
            return
        try:
            self._render_readme(text)
            self.readme_bin.set_visible(True)
        except Exception as e:
            print(f'Pasar: README render error: {e}')

    def _render_readme(self, text):
        """Render Markdown text into the readme_view TextBuffer using TextTags."""
        import re
        buf = self.readme_view.get_buffer()
        buf.set_text('')

        # ── Text tags ─────────────────────────────────────────────────────────
        tag_table = buf.get_tag_table()

        def ensure_tag(name, **props):
            t = tag_table.lookup(name)
            if t is None:
                t = buf.create_tag(name, **props)
            return t

        ensure_tag('h1', weight=700, scale=1.5, pixels_above_lines=10, pixels_below_lines=4)
        ensure_tag('h2', weight=700, scale=1.25, pixels_above_lines=8, pixels_below_lines=3)
        ensure_tag('h3', weight=700, scale=1.1, pixels_above_lines=6, pixels_below_lines=2)
        ensure_tag('bold', weight=700)
        ensure_tag('italic', style=2)   # Pango.Style.ITALIC
        ensure_tag('code', family='Monospace', scale=0.9)
        ensure_tag('blockquote', foreground='gray', left_margin=16)

        # ── Pre-processing ────────────────────────────────────────────────────
        # Strip HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        # Strip linked images: [![alt](img)](url)  — must be done BEFORE plain images
        text = re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)', '', text)

        # Strip plain images: ![alt](url) and ![alt][ref]
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
        text = re.sub(r'!\[[^\]]*\]\[[^\]]*\]', '', text)

        # Strip HTML img tags
        text = re.sub(r'<img\s[^>]*/?>','', text, flags=re.IGNORECASE)

        # Strip other HTML block tags we can't render (details/summary/div etc.)
        text = re.sub(r'</?(?:details|summary|div|span|p|br|hr|table|thead|tbody|tr|td|th)[^>]*>', '', text, flags=re.IGNORECASE)

        # Collapse lines that are now blank
        text = re.sub(r'\n[ \t]*\n[ \t]*\n', '\n\n', text)

        # ── Append helper ─────────────────────────────────────────────────────
        it = buf.get_end_iter()

        def append(s, tag_name=None):
            nonlocal it
            mark = buf.create_mark(None, it, True)
            buf.insert(it, s)
            if tag_name:
                start = buf.get_iter_at_mark(mark)
                buf.apply_tag_by_name(tag_name, start, it)
            buf.delete_mark(mark)

        def render_inline(line, default_tag=None):
            """Render a line with inline bold/italic/code tags."""
            segments = re.split(r'(\*\*[^*\n]+\*\*|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`)', line)
            for seg in segments:
                if not seg:
                    continue
                if seg.startswith('**') and seg.endswith('**') and len(seg) > 4:
                    append(seg[2:-2], 'bold')
                elif len(seg) > 2 and ((seg.startswith('*') and seg.endswith('*')) or
                                        (seg.startswith('_') and seg.endswith('_'))):
                    append(seg[1:-1], 'italic')
                elif seg.startswith('`') and seg.endswith('`') and len(seg) > 2:
                    append(seg[1:-1], 'code')
                else:
                    # Strip markdown links: [text](url) → text
                    clean = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', seg)
                    # Strip reference links: [text][ref] → text
                    clean = re.sub(r'\[([^\]]+)\]\[[^\]]*\]', r'\1', clean)
                    append(clean, default_tag)

        # ── Line-by-line rendering ─────────────────────────────────────────────
        in_code_block = False
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            # Fenced code blocks
            if line.startswith('```') or line.startswith('~~~'):
                in_code_block = not in_code_block
                if not in_code_block:
                    append('\n')
                i += 1
                continue

            if in_code_block:
                append(line + '\n', 'code')
                i += 1
                continue

            # Setext headings (underlined with === or ---)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.match(r'^=+\s*$', next_line) and line.strip():
                    append(re.sub(r'[`*_]', '', line.strip()) + '\n', 'h1')
                    i += 2
                    continue
                if re.match(r'^-+\s*$', next_line) and line.strip():
                    append(re.sub(r'[`*_]', '', line.strip()) + '\n', 'h2')
                    i += 2
                    continue

            # ATX headings: # ## ###
            h = re.match(r'^(#{1,3})\s+(.*)', line)
            if h:
                level = len(h.group(1))
                heading_text = re.sub(r'[`*_]|#+\s*$', '', h.group(2)).strip()
                append(heading_text + '\n', f'h{level}')
                i += 1
                continue

            # Horizontal rules → blank line
            if re.match(r'^[-*_]{3,}\s*$', line):
                append('\n')
                i += 1
                continue

            # Skip remaining HTML tags on their own line
            if re.match(r'^\s*<[^>]+>\s*$', line):
                i += 1
                continue

            # Blockquote lines
            bq = re.match(r'^>\s?(.*)', line)
            if bq:
                render_inline(bq.group(1), 'blockquote')
                append('\n')
                i += 1
                continue

            # Bullet list items
            bullet = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            if bullet:
                indent = bullet.group(1)
                rest = bullet.group(2)
                append(indent + '• ')
                render_inline(rest)
                append('\n')
                i += 1
                continue

            # Numbered list items
            numbered = re.match(r'^(\s*)\d+\.\s+(.*)', line)
            if numbered:
                indent = numbered.group(1)
                rest = numbered.group(2)
                append(indent)
                render_inline(rest)
                append('\n')
                i += 1
                continue

            # Blank line
            if not line.strip():
                append('\n')
                i += 1
                continue

            # Normal paragraph text
            render_inline(line)
            append('\n')
            i += 1



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
