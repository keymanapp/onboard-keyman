# -*- coding: utf-8 -*-

# Copyright © 2012-2017 marmuta <marmvta@gmail.com>
#
# This file is part of Onboard.
#
# Onboard is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Onboard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


from __future__ import division, print_function, unicode_literals

import collections

from Onboard.AtspiStateTracker import AtspiStateTracker
from Onboard.HardwareSensorTracker import HardwareSensorTracker
from Onboard.UDevTracker       import UDevTracker
from Onboard.utils             import Rect
from Onboard.Timer             import TimerOnce
from Onboard.definitions       import RepositionMethodEnum

import logging
_logger = logging.getLogger("AutoShow")

from Onboard.Config import Config
config = Config()


class AutoShow(object):
    """
    Auto-show and hide Onboard.
    """

    # Delay from the last focus event until the keyboard is shown/hidden.
    # Raise it to reduce unnecessary transitions (flickering).
    # Lower it for more immediate reactions.
    SHOW_REACTION_TIME = 0.0
    HIDE_REACTION_TIME = 0.3

    _keyboard = None

    _lock_visible = False
    _locks = None

    _atspi_state_tracker = None
    _hw_sensor_tracker = None
    _udev_tracker = None

    def __init__(self, keyboard):
        self._keyboard = keyboard
        self._auto_show_timer = TimerOnce()
        self._active_accessible = None
        self._locks = collections.OrderedDict()

    def reset(self):
        self._auto_show_timer.stop()
        self.unlock_all()

    def cleanup(self):
        self.reset()
        self.enable(False)  # disconnect events

    def update(self):
        self.enable_(config.is_auto_show_enabled())

    def enable(self, enable):
        if enable:
            if not self._atspi_state_tracker:
                self._atspi_state_tracker = AtspiStateTracker()
                self._atspi_state_tracker.connect(
                    "text-entry-activated", self._on_text_entry_activated)
                self._atspi_state_tracker.connect(
                    "text-caret-moved", self._on_text_caret_moved)
        else:
            if self._atspi_state_tracker:
                self._atspi_state_tracker.disconnect(
                    "text-entry-activated", self._on_text_entry_activated)
                self._atspi_state_tracker.disconnect(
                    "text-caret-moved", self._on_text_caret_moved)
            self._atspi_state_tracker = None
            self._active_accessible = None  # stop using _atspi_state_tracker

        if enable:
            self._lock_visible = False
            self._locks.clear()

        self.enable_tablet_mode_detection(
            enable and config.is_tablet_mode_detection_enabled())

        self.enable_keyboard_device_detection(
            enable and config.is_keyboard_device_detection_enabled())

    def enable_tablet_mode_detection(self, enable):
        if enable:
            if not self._hw_sensor_tracker:
                self._hw_sensor_tracker = HardwareSensorTracker()
                self._hw_sensor_tracker.connect(
                    "tablet-mode-changed", self._on_tablet_mode_changed)

            # Run/stop GlobalKeyListener when tablet-mode-enter-key or
            # tablet-mode-leave-key change.
            self._hw_sensor_tracker.update_sensor_sources()
        else:
            if self._hw_sensor_tracker:
                self._hw_sensor_tracker.disconnect(
                    "tablet-mode-changed", self._on_tablet_mode_changed)
            self._hw_sensor_tracker = None

        _logger.debug("enable_tablet_mode_detection {} {}"
                      .format(enable, self._hw_sensor_tracker))

    def enable_keyboard_device_detection(self, enable):
        """
        Detect if physical keyboard devices are present in the system.
        When detected, auto-show is locked.
        """
        if enable:
            if not self._udev_tracker:
                self._udev_tracker = UDevTracker()
                self._udev_tracker.connect(
                    "keyboard-detection-changed",
                    self._on_keyboard_device_detection_changed)
        else:
            if self._udev_tracker:
                self._udev_tracker.disconnect(
                    "keyboard-detection-changed",
                    self._on_keyboard_device_detection_changed)
            self._udev_tracker = None

        _logger.debug("enable_keyboard_device_detection {} {}"
                      .format(enable, self._udev_tracker))

    def lock(self, reason, duration, lock_show, lock_hide):
        """
        Lock showing and/or hiding the keyboard window.
        There is a separate, independent lock for each unique "reason".
        If duration is specified, automatically unlock after these number of
        seconds.
        """
        class AutoShowLock:
            timer = None
            lock_show = True
            lock_hide = True
            visibility_change = None

        # Discard pending hide/show actions.
        self._auto_show_timer.stop()

        lock = self._locks.setdefault(reason, AutoShowLock())

        if lock.timer:
            lock.timer.stop()

        if duration is None:
            lock.timer = None
        else:
            lock.timer = TimerOnce()
            lock.timer.start(duration, self._on_lock_timer, reason)

        lock.lock_show = lock_show
        lock.lock_hide = lock_hide

        _logger.debug("lock({}): {}"
                      .format(repr(reason), list(self._locks.keys())))

    def unlock(self, reason):
        """
        Remove a specific lock named by "reason".
        Returns the change in visibility that occurred while this lock was
        active. None for no change.
        """
        result = None
        lock = self._locks.get(reason)
        if lock:
            result = lock.visibility_change
            if lock.timer:
                lock.timer.stop()
            del self._locks[reason]

        _logger.debug("unlock({}) {}"
                      .format(repr(reason), list(self._locks.keys())))

        return result

    def unlock_all(self):
        """
        Remove all locks.
        """
        for lock in self._locks.values():
            if lock.timer:
                lock.timer.stop()
        self._locks.clear()

    def _on_lock_timer(self, reason):
        self.unlock(reason)
        return False

    def is_locked(self, reason):
        return reason in self._locks

    def is_show_locked(self):
        for lock in self._locks.values():
            if lock.lock_show:
                return True
        return False

    def is_hide_locked(self):
        for lock in self._locks.values():
            if lock.lock_hide:
                return True
        return False

    def lock_visible(self, lock, thaw_time=1.0):
        """
        Lock window permanently visible in response to the user showing it.
        Optionally freeze hiding/showing for a limited time.
        """
        _logger.debug("lock_visible{} ".format((lock, thaw_time)))

        # Permanently lock visible.
        self._lock_visible = lock

        # Temporarily stop showing/hiding.
        if thaw_time:
            self.lock("lock_visible", thaw_time, True, True)

        # Leave the window in its current state,
        # discard pending hide/show actions.
        self._auto_show_timer.stop()

        # Stop pending auto-repositioning
        if lock:
            self._keyboard.stop_auto_positioning()

    def is_text_entry_active(self):
        return bool(self._active_accessible)

    def can_hide_keyboard(self):
        if _logger.isEnabledFor(logging.INFO):
            msg = "locks={} " \
                .format([reason for reason, lock in self._locks.items()
                        if lock.lock_hide])

            _logger.info("can_hide_keyboard: " + msg)

        return not self.is_hide_locked()

    def can_show_keyboard(self):
        result = True

        msg = ""
        if _logger.isEnabledFor(logging.INFO):
            msg += "locks={} " \
                .format([reason for reason, lock in self._locks.items()
                        if lock.lock_show])

        if self._locks:
            result = False
        else:
            if config.is_tablet_mode_detection_enabled():
                tablet_mode = self._hw_sensor_tracker.get_tablet_mode() \
                    if self._hw_sensor_tracker else None

                msg += "tablet_mode={} ".format(tablet_mode)

                result = result and \
                    tablet_mode is not False  # can be True, False or None

            if config.is_keyboard_device_detection_enabled():
                detected = self._udev_tracker.is_keyboard_device_detected() \
                    if self._udev_tracker else None

                msg += "keyboard_device_detected={} ".format(detected)

                result = result and \
                    detected is not True  # can be True, False or None

        _logger.info("can_show_keyboard: " + msg)

        return result

    def _on_text_caret_moved(self, event):
        """
        Show the keyboard on click of an already focused text entry
        (LP: 1078602). Do this only for single line text entries to
        still allow clicking longer documents without having onboard show up.
        """
        if config.auto_show.enabled and \
           not self._keyboard.is_visible():

            accessible = self._active_accessible
            if accessible:
                if accessible.is_single_line():
                    self._on_text_entry_activated(accessible)

    def _on_text_entry_activated(self, accessible):
        self._active_accessible = accessible
        active = bool(accessible)

        self.request_keyboard_visible(active)

    def _on_tablet_mode_changed(self, active):
        self._handle_tablet_mode_changed(active)

    def _on_keyboard_device_detection_changed(self, detected):
        self._handle_tablet_mode_changed(not detected)

    def _handle_tablet_mode_changed(self, tablet_mode_active):
        if tablet_mode_active:
            show = self.is_text_entry_active()
        else:
            # hide keyboard even if it was locked visible
            self.lock_visible(False, thaw_time=0)
            show = False

        self.request_keyboard_visible(show)

    def request_keyboard_visible(self, visible, delay=None):
        # Remember request per lock. That way we know the time span in
        # which the visibility change occurred.
        for lock in self._locks.values():
            lock.visibility_change = visible

        # Always allow to show the window even when locked.
        # Mitigates right click on unity-2d launcher hiding
        # onboard before _lock_visible is set (Precise).
        if self._lock_visible:
            visible = True

        can_hide = self.can_hide_keyboard()
        can_show = self.can_show_keyboard()

        _logger.debug("request_keyboard_visible({}): lock_visible={} "
                      "can_hide={} can_show={}"
                      .format(visible, self._lock_visible, can_hide, can_show))

        if visible is False and can_hide or \
           visible is True  and can_show:
            self.show_keyboard(visible, delay)

        # The active accessible changed, stop trying to
        # track the position of the previous one.
        # -> less erratic movement during quick focus changes
        self._keyboard.stop_auto_positioning()

    def show_keyboard(self, show, delay=None):
        """ Begin AUTO_SHOW or AUTO_HIDE transition """
        if delay is None:
            # Don't act on each and every focus message. Delay the start
            # of the transition slightly so that only the last of a bunch of
            # focus messages is acted on.
            delay = (self.SHOW_REACTION_TIME if show else
                     self.HIDE_REACTION_TIME)

        if delay == 0:
            self._auto_show_timer.stop()
            self._begin_transition(show)
        else:
            self._auto_show_timer.start(delay, self._begin_transition, show)

    def _begin_transition(self, show):
        self._keyboard.transition_visible_to(show)
        if show:
            self._keyboard.auto_position()
        self._keyboard.commit_transition()
        return False

    def get_repositioned_window_rect(self, view, home, limit_rects,
                                     test_clearance, move_clearance,
                                     horizontal=True, vertical=True):
        """
        Get the alternative window rect suggested by auto-show or None if
        no repositioning is required.
        """
        accessible = self._active_accessible
        if not accessible:
            return None

        accessible.invalidate_extents()
        acc_rect = accessible.get_extents()
        if acc_rect.is_empty() or \
           self._lock_visible:
            return None

        method = config.get_auto_show_reposition_method()
        x = None
        y = None

        # The home_rect doesn't include window decoration,
        # make sure to add decoration for correct clearance.
        rh = home.copy()
        window = view.get_kbd_window()
        if window:
            offset = window.get_client_offset()
            rh.w += offset[0]
            rh.h += offset[1]

        # "Follow active window" method
        if method == RepositionMethodEnum.REDUCE_POINTER_TRAVEL:
            frame = accessible.get_frame()
            app_rect = frame.get_extents() \
                if frame else Rect()
            x, y = self._find_close_position(view, rh,
                                             app_rect, acc_rect, limit_rects,
                                             test_clearance, move_clearance,
                                             horizontal, vertical)

        # "Only move when necessary" method
        if method == RepositionMethodEnum.PREVENT_OCCLUSION:
            x, y = self._find_non_occluding_position(view, rh,
                                                acc_rect, limit_rects,
                                                test_clearance, move_clearance,
                                                horizontal, vertical)
        if not x is None:
            return Rect(x, y, home.w, home.h)
        else:
            return None

    def _find_close_position(self, view, home,
                             app_rect, acc_rect, limit_rects,
                             test_clearance, move_clearance,
                             horizontal=True, vertical=True):
        rh = home

        # Closer clearance for toplevels. There's usually nothing
        # that can be obscured.
        move_clearance_frame = Rect(10, 10, 10, 10)

        # Leave a different clearance for the new, yet to be found, positions.
        ra = acc_rect.apply_border(*move_clearance)
        if not app_rect.is_empty():
            rp = app_rect.apply_border(*move_clearance_frame)

        # candidate positions
        vp = []
        if vertical:
            xc = acc_rect.get_center()[0] - rh.w / 2
            if app_rect.w > rh.w:
                xc = max(xc, app_rect.left())
                xc = min(xc, app_rect.right() - rh.w)

            if not app_rect.is_empty():
                # below window
                vp.append([xc, rp.bottom(), app_rect])

                # above window
                vp.append([xc, rp.top() - rh.h, app_rect])

            # inside maximized window, y at home.y
            vp.append([xc, home.y, acc_rect])

            # below text entry
            vp.append([xc, ra.bottom(), acc_rect])

            # above text entry
            vp.append([xc, ra.top() - rh.h, acc_rect])

        # limited, non-intersecting candidate rectangles
        rresult = None
        for p in vp:
            pl = view.limit_position(p[0], p[1],
                                     view.canvas_rect,
                                     limit_rects)
            r = Rect(pl[0], pl[1], rh.w, rh.h)
            ri = p[2]
            rcs = [ri, acc_rect]  # collision rects
            if not any(r.intersects(rc) for rc in rcs):
                rresult = r
                break

        if rresult is None:
            # try again, this time horizontally and vertically
            rhtmp = Rect(vp[0][0], vp[0][1], home.w, home.h)
            return self._find_non_occluding_position(view, home,
                                                acc_rect, limit_rects,
                                                test_clearance, move_clearance,
                                                horizontal, vertical)
        else:
            return rresult.get_position()

    def _find_non_occluding_position(self, view, home,
                                     acc_rect, limit_rects,
                                     test_clearance, move_clearance,
                                     horizontal = True, vertical = True):
        rh = home

        # Leave some clearance around the accessible to account for
        # window frames and position errors of firefox entries.
        ra = acc_rect.apply_border(*test_clearance)

        if rh.intersects(ra):

            # Leave a different clearance for the new,
            # yet to be found positions.
            ra = acc_rect.apply_border(*move_clearance)
            x, y = rh.get_position()

            # candidate positions
            vp = []
            if horizontal:
                vp.append([ra.left() - rh.w, y])
                vp.append([ra.right(), y])
            if vertical:
                vp.append([x, ra.top() - rh.h])
                vp.append([x, ra.bottom()])

            # limited, non-intersecting candidate rectangles
            vr = []
            for p in vp:
                pl = view.limit_position(p[0], p[1],
                                         view.canvas_rect,
                                         limit_rects)
                r = Rect(pl[0], pl[1], rh.w, rh.h)
                if not r.intersects(ra):
                    vr.append(r)

            # candidate with smallest center-to-center distance wins
            chx, chy = rh.get_center()
            dmin = None
            rmin = None
            for r in vr:
                cx, cy = r.get_center()
                dx, dy = cx - chx, cy - chy
                d2 = dx * dx + dy * dy
                if dmin is None or dmin > d2:
                    dmin = d2
                    rmin = r

            if not rmin is None:
                return rmin.get_position()

        return None, None

