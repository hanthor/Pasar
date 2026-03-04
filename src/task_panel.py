# task_panel.py - Task / download manager panel
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, Pango
from .task_manager import Task, TaskStatus, TaskOperation, TaskManager


class PasarTaskRow(Gtk.ListBoxRow):
    """A single row in the task panel showing one operation's progress."""

    __gtype_name__ = 'PasarTaskRow'

    def __init__(self, task, **kwargs):
        super().__init__(**kwargs)
        self._task = task

        self.set_activatable(False)
        self.set_selectable(False)

        # ── Layout ───────────────────────────────────────
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        outer.set_margin_start(4)
        outer.set_margin_end(4)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)

        # Icon for the operation
        self._icon = Gtk.Image(pixel_size=32)
        self._icon.add_css_class('dim-label')
        outer.append(self._icon)

        # Info column
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)

        # Title
        self._title_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._title_label.add_css_class('heading')
        info.append(self._title_label)

        # Status text
        self._status_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._status_label.add_css_class('caption')
        self._status_label.add_css_class('dim-label')
        info.append(self._status_label)

        # Progress bar
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class('task-progress')
        info.append(self._progress_bar)

        outer.append(info)

        # Status icon (right side) — checkmark / error / spinner
        self._status_icon_box = Gtk.Box(valign=Gtk.Align.CENTER)
        self._spinner = Adw.Spinner()
        self._spinner.set_size_request(20, 20)
        self._done_icon = Gtk.Image(icon_name='object-select-symbolic', pixel_size=20)
        self._done_icon.add_css_class('success')
        self._done_icon.set_visible(False)
        self._error_icon = Gtk.Image(icon_name='dialog-error-symbolic', pixel_size=20)
        self._error_icon.add_css_class('error')
        self._error_icon.set_visible(False)

        self._status_icon_box.append(self._spinner)
        self._status_icon_box.append(self._done_icon)
        self._status_icon_box.append(self._error_icon)
        outer.append(self._status_icon_box)

        self.set_child(outer)

        # Connect task signals
        self._bindings = []
        task.connect('notify::status', self._on_task_changed)
        task.connect('notify::progress', self._on_task_changed)
        task.connect('notify::status-text', self._on_task_changed)

        self._update()

    @property
    def task(self):
        return self._task

    def _on_task_changed(self, *args):
        self._update()

    def _update(self):
        task = self._task

        # Icon
        if task.operation == TaskOperation.INSTALL:
            self._icon.set_from_icon_name('folder-download-symbolic')
        elif task.operation == TaskOperation.REMOVE:
            self._icon.set_from_icon_name('user-trash-symbolic')
        else:
            self._icon.set_from_icon_name('software-update-available-symbolic')

        # Title
        self._title_label.set_label(task.title)

        # Status text
        self._status_label.set_label(task.status_text)

        # Progress bar
        if task.status == TaskStatus.RUNNING:
            self._progress_bar.set_visible(True)
            if task.progress > 0:
                self._progress_bar.set_fraction(task.progress)
            else:
                self._progress_bar.pulse()
        elif task.status == TaskStatus.PENDING:
            self._progress_bar.set_visible(True)
            self._progress_bar.set_fraction(0.0)
        else:
            self._progress_bar.set_visible(False)

        # Right-side indicator
        is_active = task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
        is_done = task.status == TaskStatus.COMPLETED
        is_err = task.status == TaskStatus.FAILED

        self._spinner.set_visible(is_active)
        self._done_icon.set_visible(is_done)
        self._error_icon.set_visible(is_err)

        # Show error detail as tooltip
        if is_err and task.error_detail:
            self.set_tooltip_text(task.error_detail)
        else:
            self.set_tooltip_text(None)


@Gtk.Template(resource_path='/dev/hanthor/Pasar/task-panel.ui')
class PasarTaskPanel(Adw.Dialog):
    """Dialog that displays all active and recent tasks with progress."""

    __gtype_name__ = 'PasarTaskPanel'

    panel_stack = Gtk.Template.Child()
    task_list_box = Gtk.Template.Child()
    clear_button = Gtk.Template.Child()

    def __init__(self, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._task_manager = task_manager
        self._rows = {}  # task -> PasarTaskRow

        self.clear_button.connect('clicked', self._on_clear_clicked)

        if task_manager:
            self._connect_manager(task_manager)

    def _connect_manager(self, mgr):
        mgr.connect('task-added', self._on_task_added)
        mgr.connect('task-finished', self._on_task_finished)
        # Populate with existing tasks
        for task in mgr.tasks:
            self._add_task_row(task)
        self._update_stack()

    def _on_task_added(self, mgr, task):
        self._add_task_row(task)
        self._update_stack()

    def _on_task_finished(self, mgr, task):
        self._update_clear_button()

    def _add_task_row(self, task):
        if task in self._rows:
            return
        row = PasarTaskRow(task)
        self._rows[task] = row
        # Prepend (newest first)
        self.task_list_box.prepend(row)
        self._update_stack()

    def _update_stack(self):
        if self._rows:
            self.panel_stack.set_visible_child_name('tasks')
        else:
            self.panel_stack.set_visible_child_name('empty')
        self._update_clear_button()

    def _update_clear_button(self):
        has_done = any(
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            for t in self._rows
        )
        self.clear_button.set_visible(has_done)

    def _on_clear_clicked(self, button):
        to_remove = [
            t for t in self._rows
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        for task in to_remove:
            row = self._rows.pop(task)
            self.task_list_box.remove(row)
        self._update_stack()
