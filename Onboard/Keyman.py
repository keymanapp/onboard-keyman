# -*- coding: utf-8 -*-

# Copyright © 2018 Daniel Glassey <dglassey@gmail.com>
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
Monitoring keyman keyboard
"""

from __future__ import division, print_function, unicode_literals

try:
    import dbus
except ImportError:
    pass

from Onboard.utils import Modifiers

from Onboard.Version import require_gi_versions
require_gi_versions()
from gi.repository       import GObject
from lxml import etree

### Logging ###
import logging
_logger = logging.getLogger("OnboardKeyman")
###############

    # class KeymanDBus(GObject.GObject):
    #     __gsignals__ = {
    #         'keyman-changed': (GObject.SIGNAL_RUN_FIRST, None, ())
    #     }

    #     def __init__(self, bus):
    #         GObject.GObject.__init__(self)
    #         self.key_labels = None
    #         self.keyboard = None
    #         self.name = "None"
    #         self.bus = bus

    #     def set_labels(self):
    #         self.key_labels = KeymanLabels()
    #         self.key_labels.parse_labels("/usr/local/share/keyman/test.ldml")

    #     def unset_labels(self):
    #         self.key_labels = None

    #     def on_keyboard_changed(keyboardid):
    #         #reload_labels()
    #         self.emit("keyman-changed", keyboardid)


class KeymanDBus(GObject.GObject):
    """
    Keyman D-bus control and signal handling.
    """
    __gsignals__ = {
        str('keyman-changed'): (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, ())
    }

#    MOUSE_A11Y_SCHEMA_ID = "org.gnome.desktop.a11y.mouse"
    KEYMAN_SCHEMA_ID = "com.Keyman"

    KM_DBUS_NAME  = "com.Keyman"
    KM_DBUS_PATH  = "/com/Keyman/IBus"
    KM_DBUS_IFACE = "com.Keyman"
    KM_DBUS_PROP_LDML  = "LDMLFile"
    KM_DBUS_PROP_NAME  = "Name"

    def __init__(self):
        GObject.GObject.__init__(self)
        self.key_labels = None
        # self.keyboard = None
        self.name = "None"
        # self.bus = bus
        self._name_callbacks = []

        if not "dbus" in globals():
            raise ImportError("python-dbus unavailable")

        # ConfigObject.__init__(self)
        # ClickSimulator.__init__(self)

        # self.launcher = DelayedLauncher()
        # self._daemon_running_notify_callbacks = []

        # Check if mousetweaks' schema is installed.
        # Raises SchemaError if it isn't.
        # self.mousetweaks = ConfigObject(None, self.MOUSETWEAKS_SCHEMA_ID)

        # connect to session bus
        try:
            self._bus = dbus.SessionBus()
        except dbus.exceptions.DBusException:
            raise RuntimeError("D-Bus session bus unavailable")
        self._bus.add_signal_receiver(self._on_name_owner_changed,
                                      "NameOwnerChanged",
                                      dbus.BUS_DAEMON_IFACE,
                                      arg0=self.KM_DBUS_NAME)
        # Initial state
        proxy = self._bus.get_object(dbus.BUS_DAEMON_NAME, dbus.BUS_DAEMON_PATH)
        result = proxy.NameHasOwner(self.KM_DBUS_NAME, dbus_interface=dbus.BUS_DAEMON_IFACE)
        self._set_connection(bool(result))

    # def _init_keys(self):
    #     """ Create gsettings key descriptions """

    #     self.schema = self.MOUSE_A11Y_SCHEMA_ID
    #     self.sysdef_section = None

    #     self.add_key("dwell-click-enabled", False)
    #     self.add_key("dwell-time", 1.2)
    #     self.add_key("dwell-threshold", 10)
    #     self.add_key("click-type-window-visible", False)

    # def on_properties_initialized(self):
    #     ConfigObject.on_properties_initialized(self)

    #     # launch mousetweaks on startup if necessary
    #     if not self._iface and \
    #        self.dwell_click_enabled:
    #         self._launch_daemon(0.5)

    # def cleanup(self):
    #     self._daemon_running_notify_callbacks = []

    # def _launch_daemon(self, delay):
    #     self.launcher.launch_delayed(["mousetweaks"], delay)

    def _set_connection(self, active):
        ''' Update interface object, state and notify listeners '''
        if active:
            proxy = self._bus.get_object(self.KM_DBUS_NAME, self.KM_DBUS_PATH)
            self._iface = dbus.Interface(proxy, dbus.PROPERTIES_IFACE)
            self._iface.connect_to_signal("PropertiesChanged",
                                          self._on_name_prop_changed)
            self._LDMLFile = self._iface.Get(self.KM_DBUS_IFACE, self.KM_DBUS_PROP_LDML)
            self.name = self._iface.Get(self.KM_DBUS_IFACE, self.KM_DBUS_PROP_NAME)
            # self._click_type = self._iface.Get(self.MT_DBUS_IFACE, self.MT_DBUS_PROP)
            if self._LDMLFile and self.name != "None":
                self.key_labels = KeymanLabels()
                self.key_labels.parse_labels(self._LDMLFile)
            else:
                self.key_labels = None
        else:
            self._iface = None
            self.name = "None"
            self._LDMLFile = None
            self.key_labels = None
            # self._click_type = self.CLICK_TYPE_SINGLE

    def _on_name_owner_changed(self, name, old, new):
        '''
        The daemon has de/registered the name.
        Called when ibus-kmfl un/loads a keyboard
        '''
        active = old == ""
        # if active:
        #     self.launcher.stop()
        self._set_connection(active)

        # update hover click button
        # for callback in self._daemon_running_notify_callbacks:
        #     callback(active)

    # def daemon_running_notify_add(self, callback):
    #     self._daemon_running_notify_callbacks.append(callback)

    def _on_name_prop_changed(self, iface, changed_props, invalidated_props):
        ''' The Keyboard name has changed.'''
        if self.KM_DBUS_PROP_NAME in changed_props:
            self.name = changed_props.get(self.KM_DBUS_PROP_NAME)
            self._LDMLFile = self._iface.Get(self.KM_DBUS_IFACE, self.KM_DBUS_PROP_LDML)
            # self._click_type = self._iface.Get(self.MT_DBUS_IFACE, self.MT_DBUS_PROP)
            if self._LDMLFile and self.name != "None":
                self.key_labels = KeymanLabels()
                self.key_labels.parse_labels(self._LDMLFile)
            else:
                self.key_labels = None

            # notify listeners
            for callback in self._name_callbacks:
                callback(self.name)

    # def set_labels(self):
    #     self.key_labels = KeymanLabels()
    #     self.key_labels.parse_labels("/usr/local/share/keyman/test.ldml")

    # def unset_labels(self):
    #     self.key_labels = None

    def on_keyboard_changed(self, keyboardid):
        #reload_labels()
        self.emit("keyman-changed", keyboardid)

    # def _on_click_type_prop_changed(self, iface, changed_props, invalidated_props):
    #     ''' Either we or someone else has change the click-type. '''
    #     if self.MT_DBUS_PROP in changed_props:
    #         self._click_type = changed_props.get(self.MT_DBUS_PROP)

    #         # notify listeners
    #         for callback in self._click_type_callbacks:
    #             callback(self._click_type)

    # def _get_mt_click_type(self):
    #     return self._click_type;

    # def _set_mt_click_type(self, click_type):
    #     if click_type != self._click_type:# and self.is_active():
    #         self._click_type = click_type
    #         self._iface.Set(self.MT_DBUS_IFACE, self.MT_DBUS_PROP, click_type)

    # def _click_type_to_mt(self, button, click_type):
    #     if click_type == self.CLICK_TYPE_SINGLE:
    #         if button == self.PRIMARY_BUTTON:
    #             return self.MT_CLICK_TYPE_PRIMARY
    #         elif button == self.MIDDLE_BUTTON:
    #             return self.MT_CLICK_TYPE_MIDDLE
    #         elif button == self.SECONDARY_BUTTON:
    #             return self.MT_CLICK_TYPE_SECONDARY
    #         else:
    #             return None
    #     elif click_type == self.CLICK_TYPE_DOUBLE:
    #         if button == self.PRIMARY_BUTTON:
    #             return self.MT_CLICK_TYPE_DOUBLE
    #         else:
    #             return None
    #     elif click_type == self.CLICK_TYPE_DRAG:
    #         if button == self.PRIMARY_BUTTON:
    #             return self.MT_CLICK_TYPE_DRAG
    #         else:
    #             return None
    #     else:
    #         return None

    # def _click_type_from_mt(self, mt_click_type):
    #     if mt_click_type == self.MT_CLICK_TYPE_PRIMARY:
    #         return self.PRIMARY_BUTTON, self.CLICK_TYPE_SINGLE
    #     elif mt_click_type == self.MT_CLICK_TYPE_MIDDLE:
    #         return self.MIDDLE_BUTTON, self.CLICK_TYPE_SINGLE
    #     elif mt_click_type == self.MT_CLICK_TYPE_SECONDARY:
    #         return self.SECONDARY_BUTTON, self.CLICK_TYPE_SINGLE
    #     elif mt_click_type == self.MT_CLICK_TYPE_DOUBLE:
    #         return self.PRIMARY_BUTTON, self.CLICK_TYPE_DOUBLE
    #     elif mt_click_type == self.MT_CLICK_TYPE_DRAG:
    #         return self.PRIMARY_BUTTON, self.CLICK_TYPE_DRAG
    #     else:
    #         return None, None

    ##########
    # Public
    ##########

    def state_notify_add(self, callback):
        """ Convenience function to subscribes to all notifications """
        # self.dwell_click_enabled_notify_add(callback)
        self.name_notify_add(callback)
        # self.daemon_running_notify_add(callback)

    def name_notify_add(self, callback):
        self._name_callbacks.append(callback)

    def is_active(self):
        # return self.dwell_click_enabled_enabled and bool(self._iface)
        return bool(self._iface)

    # def set_active(self, active):
    #     self.dwell_click_enabled = active

    #     # try to launch mousetweaks if it isn't running yet
    #     if active and not self._iface:
    #         self._launch_daemon(1.0)
    #     else:
    #         self.launcher.stop()

    # def supports_click_params(self, button, click_type):
    #     # mousetweaks since 3.3.90 supports middle click button too.
    #     return True

    # def map_primary_click(self, event_source, button, click_type):
    #     mt_click_type = self._click_type_to_mt(button, click_type)
    #     if not mt_click_type is None:
    #         self._set_mt_click_type(mt_click_type)

    # def get_click_button(self):
    #     mt_click_type = self._get_mt_click_type()
    #     button, click_type = self._click_type_from_mt(mt_click_type)
    #     return button

    # def get_click_type(self):
    #     mt_click_type = self._get_mt_click_type()
    #     button, click_type = self._click_type_from_mt(mt_click_type)
    #     return click_type

class KeymanLabels():
    keymankeys = {}
    # keymanlabels is a dict of modmask : label (and also has "code" : keycode?)
    # keymankeys is a dict of keycode : keymanlabels

    def parse_labels(self, ldmlfile):
        tree = etree.parse(ldmlfile)
        root = tree.getroot()
        keymaps = tree.findall('keyMap')

        for keymap in keymaps:
            if keymap.attrib:
                # if there is more than one modifier set split it here
                # because will need to duplicate the label set
                keyman_modifiers = self.convert_ldml_modifiers_to_onboard(keymap.attrib['modifiers'])
            else:
                # print("No modifiers")
                keyman_modifiers = (0,)
            maps = keymap.findall('map')
            for map in maps:
                for keymanmodifier in keyman_modifiers:
                    iso = "A" + map.attrib['iso']
                    if iso == "AA03":
                        iso = "SPCE"
                    elif iso == "AE00":
                        iso = "TLDE"
                    elif iso == "AB00":
                        iso = "LSGT"
                    elif iso == "AC12":
                        iso = "BKSL"
                    if not iso in self.keymankeys:
                        self.keymankeys[iso] = { keymanmodifier : map.attrib['to'] } # .encode('utf-8')}
                    else:
                        self.keymankeys[iso][keymanmodifier] = map.attrib['to'] # .encode('utf-8')

    def labels_from_id(self, id):
        if id in self.keymankeys:
            # print("id ", id, "is:")
            # print(self.keymankeys[id])
            return self.keymankeys[id]
        else:
            print("unknown key id: ", id)
            return {}

    def convert_ldml_modifiers_to_onboard(self, modifiers):
        list_modifiers = modifiers.split(" ")
        keyman_modifiers = ()
        for modifier in list_modifiers:
            keymanmod = 0
            keys = modifier.split("+")
            for key in keys:
                if "shift" == key:
                    keymanmod |= Modifiers.SHIFT
                if "altR" == key:
                    keymanmod |= Modifiers.ALTGR
                if "ctrlR" == key:
                    keymanmod |= Modifiers.MOD3
                if "ctrlL" == key:
                    keymanmod |= Modifiers.CTRL
                if "ctrl" == key:
                    keymanmod |= Modifiers.CTRL
                if "altL" == key:
                    keymanmod |= Modifiers.ALT
                if "alt" == key:
                    keymanmod |= Modifiers.ALT
            keyman_modifiers = keyman_modifiers + (keymanmod,)
        return keyman_modifiers
