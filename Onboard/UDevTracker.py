# -*- coding: utf-8 -*-

# Copyright © 2017 marmuta <marmvta@gmail.com>
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

from Onboard.utils import EventSource
import Onboard.osk as osk

import logging
_logger = logging.getLogger("UDevTracker")

from Onboard.Config import Config
config = Config()


class UDevTracker(EventSource):
    """ Singleton class that keeps track of UDev devices. """

    _event_names = ("keyboard-detection-changed",)

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
        self._udev = None
        self._keyboard_device_detected = None

    def cleanup(self):
        EventSource.cleanup(self)
        self._register_listeners(False)

    def connect(self, event_name, callback):
        EventSource.connect(self, event_name, callback)
        self.update_event_sources()

    def disconnect(self, event_name, callback):
        had_listeners = self.has_listeners(self._event_names)

        EventSource.disconnect(self, event_name, callback)
        self.update_event_sources()

        # help debugging disconnecting events on exit
        if had_listeners and not self.has_listeners(self._event_names):
            _logger.info("all listeners disconnected")

    def update_event_sources(self):
        register = self.has_listeners()
        self._register_udev_listeners(register)

    def _register_listeners(self, register):
        self._register_udev_listeners(register)

    def _register_udev_listeners(self, register):
        if bool(self._udev) != register:
            if register:
                try:
                    self._udev = osk.UDev()
                except:
                    self._udev = None

                if self._udev:
                    self._udev.connect('uevent', self._on_udev_event)

                config.auto_show. \
                    keyboard_device_detection_exceptions_notify_add(
                        lambda x: self._detect_keyboard_devices())

                self._update_keyboard_device_detected()
            else:
                config.auto_show. \
                    keyboard_device_detection_exceptions_notify_remove(
                        lambda x: self._detect_keyboard_devices())

                self._udev.disconnect('uevent', self._on_udev_event)
                self._udev = None
                self._keyboard_device_detected = None

    def _on_udev_event(self, *args):
        _logger.debug('_on_udev_event: {}'.format(args))
        self._detect_keyboard_devices()

    def _detect_keyboard_devices(self):
        keyboard_detected_before = self.is_keyboard_device_detected()
        self._update_keyboard_device_detected()
        keyboard_detected = self.is_keyboard_device_detected()

        if keyboard_detected != keyboard_detected_before:
            _logger.debug('_detect_keyboard_devices: {}'
                          .format(keyboard_detected))
            self.emit_async("keyboard-detection-changed", keyboard_detected)

    def _update_keyboard_device_detected(self):
        detected = None
        if self._udev:
            keyboard_devices = self.get_keyboard_devices()
            _logger.debug("_update_keyboard_device_detected: "
                          "keyboard_devices={}"
                          .format(keyboard_devices))
            detected = False
            for device in keyboard_devices:
                if device.id not in \
                   config.auto_show.keyboard_device_detection_exceptions:
                    detected = True

        _logger.debug("_update_keyboard_device_detected: keyboard detected={}"
                      .format(detected))
        self._keyboard_device_detected = detected

    def is_keyboard_device_detected(self):
        """
        Return value:
            True = one or more keyboard devices detected
            False = no keyboard device detected
            None = unknown
        """
        return self._keyboard_device_detected

    def get_keyboard_devices(self):
        if self._udev:
            raw_devices = self._udev.get_keyboard_devices()
            _logger.debug("get_keyboard_devices: "
                          "raw_devices={}".format(raw_devices))

            devices = []
            for i, d in enumerate(raw_devices):
                device = UDevDevice()
                name = d["NAME"].replace('"', '')
                serial = d["ID_SERIAL"].replace('"', '')

                device.id = (d["ID_VENDOR_ID"] + ":" +
                             d["ID_MODEL_ID"] + ":" +
                             (serial if serial
                              else name.replace(" ", "_")))
                device.name = name
                try:
                    device.usb_interface_num = int(d["ID_USB_INTERFACE_NUM"])
                except ValueError:
                    device.usb_interface_num = 0

                self.append_unique(devices, device)

            return devices

        return []

    def append_unique(self, devices, device):
        """
        For some devices osk_udev returns duplicate entries for different USB
        interfaces. Filter those out and keep only USB interface 0.
        """
        for i, d in enumerate(devices):
            if d.id == device.id:
                if device.usb_interface_num < d.usb_interface_num:
                    devices[i] = device
                return

        devices.append(device)


class UDevDevice:
    id = ""
    name = ""
    usb_interface_num = 0

    def __str__(self):
        return "{}(id={} name={} " \
               "usb_interface_num={})" \
               .format(type(self).__name__,
                       self.id,
                       self.name,
                       self.usb_interface_num,
                       )

    def __repr__(self):
        return self.__str__()

