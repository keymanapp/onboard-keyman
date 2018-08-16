# -*- coding: utf-8 -*-

# Copyright © 2014, 2016-2017 marmuta <marmvta@gmail.com>
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

"""
Hide the keyboard on incoming physical keyboard events.
"""

from Onboard.GlobalKeyListener  import GlobalKeyListener
from Onboard.UDevTracker        import UDevTracker

import logging
_logger = logging.getLogger("AutoHide")

from Onboard.Config import Config
config = Config()


class AutoHide:
    """
    Hide Onboard when a physical keyboard is being used.
    """
    LOCK_REASON = "hide-on-key-press"

    def __init__(self, keyboard):
        self._keyboard = keyboard
        self._key_listener = None
        self._udev_keyboard_devices = None

    def cleanup(self):
        self._register_events(False)

    def is_enabled(self):
        return self._key_listener is not None

    def enable(self, enable):
        self._register_events(enable)

    def _register_events(self, register):
        if register:
            if not self._key_listener:
                self._key_listener = GlobalKeyListener()
                self._key_listener.connect("key-press", self._on_key_press)
                self._key_listener.connect("devices-updated",
                                            self._on_devices_updated)
        else:
            if self._key_listener:
                self._key_listener.disconnect("key-press", self._on_key_press)
                self._key_listener.disconnect("devices-updated",
                                              self._on_devices_updated)
            self._key_listener = None

    def _on_devices_updated(self):
        if config.is_tablet_mode_detection_enabled():
            udev_tracker = UDevTracker()
            self._udev_keyboard_devices = udev_tracker.get_keyboard_devices()
        else:
            self._udev_keyboard_devices = None

        _logger.debug("AutoHide._on_devices_updated(): {}"
                      .format(self._udev_keyboard_devices and
                              [d.name for d in self._udev_keyboard_devices]))

    def _on_key_press(self, event):
        if config.is_auto_hide_on_keypress_enabled():

            if _logger.isEnabledFor(logging.INFO):
                # if not self._keyboard.is_auto_show_locked(self.LOCK_REASON):
                s = self._key_listener.get_key_event_string(event)
                _logger.info("_on_key_press(): {}".format(s))

            # Only react to "real" keyboard devices when tablet-mode detection
            # is enabled. Kernel drivers like ideapad-laptop can send hotkeys
            # when switching to/from tablet-mode. We want to leave these to the
            # tablet-mode detection in HardwareSensorTracker and not have them
            # interfere with auto-hide-on-keypress.
            if not config.is_tablet_mode_detection_enabled() or \
               self._is_real_keyboard_event(event):

                # no auto-hide for hotkeys configured for tablet-mode detection
                enter_keycode = config.auto_show.tablet_mode_enter_key
                leave_keycode = config.auto_show.tablet_mode_leave_key
                if event.keycode != enter_keycode and \
                   event.keycode != leave_keycode:

                    duration = config.auto_show.hide_on_key_press_pause
                    self._keyboard.auto_show_lock_and_hide(self.LOCK_REASON,
                                                           duration)

    def is_auto_show_locked(self):
        return self._keyboard.is_auto_show_locked(self.LOCK_REASON)

    def auto_show_unlock(self):
        self._keyboard.auto_show_unlock(self.LOCK_REASON)

    def _is_real_keyboard_event(self, event):
        result = True
        xidevice = event.get_source_device()

        if self._udev_keyboard_devices:
            result = False
            for udevice in self._udev_keyboard_devices:
                if xidevice.name.lower() == udevice.name.lower():
                    result = True

        _logger.debug("_is_real_keyboard_event(): "
                      "xidevice={}, udevdevices={}, result={}"
                      .format(repr(xidevice.name),
                              self._udev_keyboard_devices and
                              [d.name for d in self._udev_keyboard_devices],
                              result))

        return result

