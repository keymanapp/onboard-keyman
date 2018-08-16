# -*- coding: utf-8 -*-

# Copyright © 2016-2017 marmuta <marmvta@gmail.com>
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

from Onboard.utils         import EventSource
from Onboard.XInput        import XIDeviceManager, XIEventType, XIEventMask

import logging
_logger = logging.getLogger("GlobalKeyListener")


class GlobalKeyListener(EventSource):
    """
    Singleton class that listens to key presses not bound to a specific window.
    """

    _event_names = ("key-press",
                    "key-release",
                    "devices-updated")

    def __new__(cls, *args, **kwargs):
        """
        Singleton magic.
        """
        if not hasattr(cls, "self"):
            cls.self = object.__new__(cls, *args, **kwargs)
            cls.self.construct()
        return cls.self

    def __init__(self):
        """
        Called multiple times, don't use this.
        """
        pass

    def construct(self):
        """
        Singleton constructor, runs only once.
        """
        EventSource.__init__(self, self._event_names)

        self._device_manager = None
        self._keyboard_slave_devices = None

    def cleanup(self):
        """
        Should not need to be called as long connect and disconnect calls
        are balanced.
        """
        EventSource.cleanup(self)
        self._register_input_events_xinput(False)

    def connect(self, event_name, callback):
        EventSource.connect(self, event_name, callback)
        self._update_registered_events()

    def disconnect(self, event_name, callback):
        had_listeners = self.has_listeners()

        EventSource.disconnect(self, event_name, callback)
        self._update_registered_events()

        # help debugging disconnecting events on exit
        if had_listeners and not self.has_listeners():
            _logger.info("all listeners disconnected")

    def _update_registered_events(self):
        self._register_input_events(self.has_listeners())

    def _register_input_events(self, register):
        """
        Only for XInput currently. Extend this if we find out how to
        do it on other, non-X platforms (or with Gtk).
        """
        if not self._register_input_events_xinput(register):
            if register:
                _logger.warning(
                    "XInput event source failed to initialize.")

    def _register_input_events_xinput(self, register):
        """ Setup XInput event handling """
        success = True

        if register:
            self._device_manager = XIDeviceManager()
            if self._device_manager.is_valid():
                self._device_manager.connect("device-event",
                                             self._on_device_event)
                self._device_manager.connect("device-grab",
                                             self._on_device_grab)
                self._device_manager.connect("devices-updated",
                                             self._on_devices_updated)
                self._select_xinput_devices()
            else:
                success = False
                self._device_manager = None
        else:

            if self._device_manager:
                self._device_manager.disconnect("device-event",
                                                self._on_device_event)
                self._device_manager.disconnect("device-grab",
                                                self._on_device_grab)
                self._device_manager.disconnect("devices-updated",
                                                self._on_devices_updated)
                self._unselect_xinput_devices()
                self._device_manager = None

        return success

    def _select_xinput_devices(self):
        """ Select keyboard devices and the events we want to listen to. """

        self._unselect_xinput_devices()

        event_mask = (XIEventMask.KeyPressMask |
                      XIEventMask.KeyReleaseMask)

        devices = self._device_manager.get_client_keyboard_attached_slaves()
        _logger.info("listening to keyboard devices: {}"
                     .format([(d.name, d.id, d.get_config_string())
                              for d in devices]))
        for device in devices:
            try:
                self._device_manager.select_events(None, device, event_mask)
            except Exception as ex:
                _logger.warning("Failed to select events for device "
                                "{id}: {ex}"
                                .format(id=device.id, ex=ex))
        self._keyboard_slave_devices = devices

    def _unselect_xinput_devices(self):
        if self._keyboard_slave_devices:
            for device in self._keyboard_slave_devices:
                try:
                    self._device_manager.unselect_events(None, device)
                except Exception as ex:
                    _logger.warning("Failed to unselect events for device "
                                    "{id}: {ex}"
                                    .format(id=device.id, ex=ex))
            self._keyboard_slave_devices = None

    def _on_device_grab(self, device, event):
        """ Someone grabbed/relased a device. Update our device list. """
        self._select_xinput_devices()

    def _on_devices_updated(self):
        # re-select devices on changes to the device hierarchy
        self._select_xinput_devices()

        self.emit("devices-updated")

    def _on_device_event(self, event):
        """
        Handler for XI2 events.
        """
        event_type = event.xi_type

        if event_type == XIEventType.KeyPress:
            self.emit("key-press", event)

        elif event_type == XIEventType.KeyRelease:
            self.emit("key-release", event)

    def get_key_event_string(self, event, message=""):
        device = event.get_source_device()
        device_name = device.name if device else "None"
        return ((message + "global key-{}, keycode={}, keyval={} "
                 "from device '{}' ({})")
                .format("press"
                if event.xi_type == XIEventType.KeyPress
                else "release",
                event.keycode,
                event.keyval,
                device_name,
                event.source_id))


