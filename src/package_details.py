# package_details.py - Package info + install/remove dialog
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gdk, Gio, GLib, GObject, Pango
from .backend import Package, BrewBackend
from .task_manager import Task, TaskStatus, TaskOperation
from .logging_util import get_logger
from .screenshot_lightbox import PasarScreenshotLightbox


_log = get_logger('package_details')


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
    version_label = Gtk.Template.Child()
    license_row = Gtk.Template.Child()
    license_label = Gtk.Template.Child()
    homepage_row = Gtk.Template.Child()
    homepage_label = Gtk.Template.Child()
    type_row = Gtk.Template.Child()
    type_label = Gtk.Template.Child()
    error_label = Gtk.Template.Child()
    detail_progress_bar = Gtk.Template.Child()
    screenshot_bin = Gtk.Template.Child()
    screenshot_button = Gtk.Template.Child()
    screenshot_picture = Gtk.Template.Child()
    readme_bin = Gtk.Template.Child()
    readme_scrolled = Gtk.Template.Child()
    readme_view = Gtk.Template.Child()
    read_more_button = Gtk.Template.Child()
    debug_render_button = Gtk.Template.Child()

    def __init__(self, package=None, backend=None, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._package = package
        self._backend = backend
        self._task_manager = task_manager
        self._task = None

        self.install_button.connect('clicked', self._on_install_clicked)
        self.remove_button.connect('clicked', self._on_remove_clicked)
        self.homepage_row.connect('activate', self._on_homepage_activated)
        self.screenshot_button.connect('clicked', self._on_screenshot_clicked)
        self.read_more_button.connect('clicked', self._on_read_more_clicked)
        self.debug_render_button.connect('clicked', self._on_debug_render_clicked)

        # Set cursor for screenshot button
        self.screenshot_button.set_cursor(Gdk.Cursor.new_from_name('pointer', None))

        if package:
            _log.debug('Opening details for %s (%s)', package.name, package.pkg_type)
            self._populate(package)

    def _populate(self, package):
        from .logging_util import get_logger
        _log = get_logger('package_details')
        
        self.set_title(package.display_name or package.name)
        self.detail_name.set_label(package.name)
        self.detail_desc.set_label(package.description or 'No description available.')
        _log.debug('Setting description: %s', package.description[:50] if package.description else 'None')

        if package.display_name and package.display_name != package.name:
            self.detail_display_name.set_label(package.display_name)
            self.detail_display_name.set_visible(True)

        self.detail_type_badge.set_label(package.pkg_type)
        if package.pkg_type == 'cask':
            self.detail_type_badge.add_css_class('cask-badge')

        _log.debug('Setting version_label: %s', package.version or 'Unknown')
        self.version_label.set_label(package.version or 'Unknown')
        self.type_label.set_label(
            'Cask (GUI App / Binary)' if package.pkg_type == 'cask'
            else 'Formula (CLI / Library)'
        )

        if package.license_:
            _log.debug('Setting license: %s', package.license_)
            self.license_label.set_label(package.license_)
            self.license_row.set_visible(True)
        else:
            _log.debug('No license for %s', package.name)

        if package.homepage:
            _log.debug('Setting homepage: %s', package.homepage)
            self.homepage_label.set_label(package.homepage)
        else:
            self.homepage_row.set_sensitive(False)
            self.homepage_label.set_label('Not available')
            _log.debug('No homepage for %s', package.name)

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
                self.detail_icon.set_from_paintable(texture)
            except Exception:
                pass

    def _on_screenshot_fetched(self, package, pixbuf):
        if pixbuf and package == self._package:
            try:
                from gi.repository import Gdk
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.screenshot_picture.set_paintable(texture)
                self.screenshot_bin.set_visible(True)
                self._current_screenshot = texture
            except Exception:
                pass

    def _on_screenshot_clicked(self, button):
        if hasattr(self, '_current_screenshot') and self._current_screenshot:
            lightbox = PasarScreenshotLightbox(self._current_screenshot)
            lightbox.present_with_animation(self.get_root())

    def _on_readme_fetched(self, package, text):
        if not text or package != self._package:
            return
        try:
            self._render_readme(text)
            self.readme_bin.set_visible(True)
        except Exception as e:
            _log.warning('README render error for %s: %s', package.name, e)

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
        
        _log.debug('Rendering README, length: %d chars', len(text))

        # ── Append helper ─────────────────────────────────────────────────────
        it = buf.get_end_iter()

        def append(s, tag_name=None):
            it = buf.get_end_iter()
            if tag_name:
                buf.insert_with_tags_by_name(it, s, tag_name)
            else:
                buf.insert(it, s)

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
            append(line + '\n')
            i += 1

        # Check if we should show "Read More"
        GLib.idle_add(self._check_readme_height)

    def _check_readme_height(self):
        # Allow natural height calculation to pick up the content size
        self.readme_view.queue_resize()
        
        adj = self.readme_view.get_vadjustment()
        upper = adj.get_upper()
        _log.debug('README upper: %s', upper)
        
        if upper > 0:
            if upper > 310: # If content is larger than our truncation threshold
                self.readme_scrolled.set_max_content_height(300)
                self.read_more_button.set_visible(True)
            else:
                self.readme_scrolled.set_max_content_height(10000) # Show all
                self.read_more_button.set_visible(False)
        else:
            # If still 0, maybe the text hasn't rendered yet, try again soon
            GLib.timeout_add(100, self._check_readme_height)

    def _on_read_more_clicked(self, button):
        if self.read_more_button.get_label() == 'Read More':
            # Expand: set a very large height limit so it grows to show all text
            self.readme_scrolled.set_max_content_height(10000)
            self.read_more_button.set_label('Show Less')
            self.read_more_button.remove_css_class('read-more-button')
        else:
            # Truncate: back to 300px
            self.readme_scrolled.set_max_content_height(300)
            self.read_more_button.set_label('Read More')
            self.read_more_button.add_css_class('read-more-button')
            
        # Ensure the layout updates
        self.readme_scrolled.queue_resize()

    def _on_debug_render_clicked(self, button):
        # Show a dialog with the "debug" info about the rendered buffer
        buf = self.readme_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        
        # Count tags
        tag_stats = {}
        it = buf.get_start_iter()
        while not it.is_end():
            tags = it.get_tags()
            for t in tags:
                name = t.get_property('name') or 'unnamed'
                tag_stats[name] = tag_stats.get(name, 0) + 1
            it.forward_char()

        stats_str = "\n".join([f"{name}: {count} chars" for name, count in tag_stats.items()])
        
        from .logging_util import get_logger
        _log = get_logger('package_details')
        _log.debug('README Debug Info:\n%s', stats_str)

        msg = f"<b>Render Stats:</b>\n{stats_str}\n\n<b>Raw Text:</b>\n{text[:500]}..."
        
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            "README Render Debug",
            ""
        )
        dialog.set_body_use_markup(True)
        dialog.set_body(msg)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()



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
        _log.info('Detail task finished: %s  success=%s', task.title, success)
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
        _log.info('Install clicked: %s', self._package.name)
        task = self._task_manager.install(self._package)
        self._bind_task(task)

    def _on_remove_clicked(self, button):
        if not self._task_manager:
            return
        _log.info('Remove clicked: %s', self._package.name)
        task = self._task_manager.remove(self._package)
        self._bind_task(task)

    def _on_homepage_activated(self, row):
        if self._package and self._package.homepage:
            launcher = Gtk.UriLauncher.new(self._package.homepage)
            launcher.launch(self.get_root(), None, None, None)
