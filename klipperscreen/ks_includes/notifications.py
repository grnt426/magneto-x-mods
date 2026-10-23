import logging
import time
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango


class _Entry:
    __slots__ = ("key", "message", "level", "count", "logged", "first", "last", "last_log", "seen", "seen_at")

    def __init__(self, key, now):
        self.key = key
        self.level, self.message = key
        self.count = 0
        self.logged = 1
        self.first = self.last = self.last_log = now
        self.seen = False
        self.seen_at = now


class Notifications:
    """One non-modal toast shared by every popup message (echo, warning, error, internal).

    Local patch, 2026-10-23: the stock modal popover re-opened on every message, so a fault line
    toggling 5 times a second swallowed every tap on the screen. Rules:
      - the toast never grabs input; tapping it dismisses it
      - a repeat of the message on screen only bumps its counter (no new popup, no screen wake)
      - the toast switches message at most once per MIN_DISPLAY, unless a more severe one arrives
      - errors are never dropped: an unseen error always gets shown, and one that keeps arriving
        after being shown pops again every ERROR_REMIND seconds
      - a burst of FLOOD_COUNT messages in FLOOD_WINDOW turns the toast into a flood banner that stays
        up while it lasts; echoes/warnings that never got screen time are summarized, not replayed
      - every message is logged: the first of each episode immediately, repeats as summaries
    """
    MIN_DISPLAY = 2
    AUTOCLOSE = 10
    QUIET = 30
    ERROR_REMIND = 60
    FLOOD_WINDOW = 5
    FLOOD_COUNT = 10
    SUMMARY_EVERY = 60
    LEVEL_NAMES = {1: "echo", 2: "warning", 3: "error"}
    LEVEL_CLASSES = {1: "message_popup_echo", 2: "message_popup_warning", 3: "message_popup_error"}
    LOG = {1: logging.info, 2: logging.warning, 3: logging.error}

    def __init__(self, screen):
        self._screen = screen
        self.entries = {}
        self.arrivals = deque()
        self.flood = False
        self.shown = None
        self.switched = 0.0
        self.popover = self.button = self.text = self.meta = None
        self.tick = None

    def notify(self, message, level=3):
        if level not in self.LEVEL_NAMES:
            level = 3
        message = f"{message}"
        now = time.monotonic()
        key = (level, message)
        entry = self.entries.get(key)
        if entry is None or now - entry.last > self.QUIET:
            if entry is not None:
                self._log_repeats(entry, now)
            entry = self.entries[key] = _Entry(key, now)
            self.LOG[level](f"{self.LEVEL_NAMES[level]}: {message}")
        entry.count += 1
        entry.last = now
        self.arrivals.append(now)
        self._update_flood(now)
        if key == self.shown:
            self._refresh(now)
        else:
            self._pick(now)
        if self.tick is None:
            self.tick = GLib.timeout_add(500, self._tick)

    def close(self, widget=None):
        now = time.monotonic()
        if widget is not None:
            logging.debug("Notification dismissed")
        for entry in self.entries.values():
            if entry.seen or entry.level < 3:
                entry.seen = True
                entry.seen_at = now
        self._hide()

    def _wants_screen(self, entry, now):
        if entry.key == self.shown:
            return False
        if not entry.seen:
            return True
        return entry.level == 3 and entry.last > entry.seen_at and now - entry.seen_at >= self.ERROR_REMIND

    def _pick(self, now):
        waiting = [e for e in self.entries.values() if self._wants_screen(e, now)]
        if waiting:
            # Normal: most severe, oldest first. Flood: most severe, newest first.
            if self.flood:
                best = max(waiting, key=lambda e: (e.level, e.last))
            else:
                best = max(waiting, key=lambda e: (e.level, -e.first))
            current = self.entries.get(self.shown)
            if current is None or best.level > current.level or now - self.switched >= self.MIN_DISPLAY:
                self._show(best, now)
                return
        self._refresh(now)

    def _show(self, entry, now):
        entry.seen = True
        entry.seen_at = now
        self.shown = entry.key
        self.switched = now
        self._screen.close_screensaver()
        if self.popover is None:
            self._build()
        style = self.button.get_style_context()
        for cls in self.LEVEL_CLASSES.values():
            style.remove_class(cls)
        style.add_class(self.LEVEL_CLASSES[entry.level])
        self._refresh(now)
        self.popover.popup()
        self.popover.show_all()
        self.meta.set_visible(bool(self.meta.get_text()))

    def _hide(self):
        self.shown = None
        if self.popover is not None:
            self.popover.popdown()

    def _build(self):
        self.text = Gtk.Label(hexpand=True, vexpand=True)
        self.text.set_line_wrap(True)
        self.text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.text.set_max_width_chars(40)
        self.meta = Gtk.Label()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add(self.text)
        box.add(self.meta)
        self.button = Gtk.Button(hexpand=True, vexpand=True)
        self.button.add(box)
        self.button.connect("clicked", self.close)
        self.button.get_style_context().add_class("message_popup")
        self.popover = Gtk.Popover.new(self._screen.base_panel.titlebar)
        self.popover.set_modal(False)
        self.popover.get_style_context().add_class("message_popup_popover")
        self.popover.set_size_request(int(self._screen.width * .9), -1)
        self.popover.set_halign(Gtk.Align.CENTER)
        self.popover.add(self.button)

    def _refresh(self, now):
        entry = self.entries.get(self.shown)
        if entry is None or self.popover is None:
            return
        self.text.set_text(entry.message)
        parts = []
        if entry.count > 1:
            parts.append(f"×{entry.count}")
        if self.flood:
            parts.append(f"message flood {len(self.arrivals) / self.FLOOD_WINDOW:.0f}/s")
        waiting = sum(1 for e in self.entries.values() if self._wants_screen(e, now))
        if waiting:
            parts.append(f"+{waiting} more")
        meta = "  ·  ".join(parts)
        self.meta.set_markup(f"<small>{GLib.markup_escape_text(meta)}</small>" if meta else "")
        self.meta.set_visible(bool(meta))

    def _update_flood(self, now):
        while self.arrivals and now - self.arrivals[0] > self.FLOOD_WINDOW:
            self.arrivals.popleft()
        count = len(self.arrivals)
        if not self.flood and count >= self.FLOOD_COUNT:
            self.flood = True
            logging.warning(f"Notification flood: {count} messages in {self.FLOOD_WINDOW}s, coalescing")
        elif self.flood and count < self.FLOOD_COUNT // 2:
            self.flood = False
            skipped = 0
            for entry in self.entries.values():
                if not entry.seen and entry.level < 3:
                    entry.seen = True
                    entry.seen_at = now
                    skipped += 1
            logging.info(f"Notification flood ended ({skipped} echo/warning messages only logged)")

    def _log_repeats(self, entry, now):
        extra = entry.count - entry.logged
        if extra > 0:
            self.LOG[entry.level](f"{self.LEVEL_NAMES[entry.level]}: repeated {extra} more times "
                                  f"in {now - entry.last_log:.0f}s: {entry.message}")
            entry.logged = entry.count
        entry.last_log = now

    def _tick(self):
        now = time.monotonic()
        self._update_flood(now)
        for key, entry in list(self.entries.items()):
            idle = now - entry.last
            if idle > self.QUIET or now - entry.last_log >= self.SUMMARY_EVERY:
                self._log_repeats(entry, now)
            if idle > self.QUIET and key != self.shown:
                del self.entries[key]
        shown = self.entries.get(self.shown)
        if (shown is not None and self._screen._config.get_main_config().getboolean('autoclose_popups', True)
                and now - max(shown.last, self.switched) >= self.AUTOCLOSE):
            self._hide()
        self._pick(now)
        if not self.entries and self.shown is None:
            self.tick = None
            return False
        return True
