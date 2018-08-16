# -*- coding: utf-8 -*-

# Copyright © 2013 Gerd Kohlberger <lowfi@chello.at>
# Copyright © 2013-2016 marmuta <marmvta@gmail.com>
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

from xml.dom import minidom

try:
    import dbus
    import dbus.service
except ImportError:
    pass


class dbus_property:  # noqa: flake8
    """
    Decorator for exposing a property over D-Bus.

    Example, read-only:

        @dbus_property(dbus_interface=ITEM_IFACE, signature='s')
        def IconName(self):
            return self._icon_name

    Example, read-write:

        @dbus_property(dbus_interface=ITEM_IFACE, signature='s')
        def IconName(self):
            return self._icon_name

        @IconName.setter
        def IconName(self, value):
            self._icon_name = value
    """
    def __init__(self, dbus_interface, signature, fget=None, fset=None):
        self.dbus_interface = dbus_interface
        self.signature = signature
        self.fget = fget
        self.fset = fset

    def __call__(self, fget):
        self.fget = fget
        self.__doc__ = fget.__doc__
        self.__name__ = fget.__name__
        self.__module__ = fget.__module__
        return self.__get__(None)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.fget is None:
            raise AttributeError("unreadable attribute")
        return self.fget(obj)

    def __set__(self, obj, value):
        if self.fset is None:
            raise AttributeError("can't set attribute")
        self.fset(obj, value)

    def getter(self, fget):
        self.fget = fget
        return self

    def setter(self, fset):
        self.fset = fset
        return self

    def is_dbus_property(self):
        return True

    def get_name(self):
        """ D-Bus property name "attribute """
        return self.__name__

    def get_access(self):
        """ D-Bus property access "attribute """
        if self.fget and self.fset:
            return "readwrite"
        if self.fget:
            return "read"
        if self.fset:
            return "write"


if "dbus" in globals():
    class ServiceBase(dbus.service.Object):
        """ Base class for D-Bus services with D-Bus property support. """

        _properties = None

        class ServiceOnboardException(dbus.DBusException):
            _dbus_error_name = 'org.onboard.Exception'

        def __init__(self, bus, service_name, object_path):
            bus_name = None
            if service_name:
                bus_name = dbus.service.BusName(service_name, bus=bus)

            dbus.service.Object.__init__(self, bus, object_path, bus_name)

        @classmethod
        def _get_class_properties(cls):
            if cls._properties is None:
                properties = {}
                for name, prop in cls.__dict__.items():
                    if hasattr(prop, "is_dbus_property"):
                        name = prop.get_name()
                        iface_name = prop.dbus_interface
                        iface_props = properties.setdefault(iface_name, {})
                        iface_props[name] = prop
                cls._properties = properties

            return cls._properties

        def _get_property(self, iface_name, prop_name):
            properties = self._get_class_properties()

            try:
                iface_props = properties[iface_name]
            except KeyError:
                raise self.ServiceOnboardException(
                    'Unknown interface \'{0}\''.format(iface_name))

            try:
                prop = iface_props[prop_name]
            except KeyError:
                raise self.ServiceOnboardException(
                    ('Unknown property \'{0}\'').format(prop_name))

            return prop

        @dbus.service.method(dbus_interface=dbus.INTROSPECTABLE_IFACE,
                                out_signature='s')  # noqa: flake8
        def Introspect(self):
            properties = self._get_class_properties()

            ref = dbus.service.Object.Introspect(
                self, self._object_path, self.connection)

            with minidom.parseString(ref.replace("\n", " ")) as dom:
                for interface in dom.getElementsByTagName("interface"):
                    iface_name = interface.attributes["name"].value
                    for name, prop in properties.get(iface_name, {}).items():
                        if prop.dbus_interface == iface_name:
                            node = dom.createElement("property")
                            node.setAttribute("name", prop.get_name())
                            node.setAttribute("type", prop.signature)
                            node.setAttribute("access", prop.get_access())
                            interface.appendChild(node)

                ref = '\n'.join([line for line
                                 in dom.toprettyxml(indent='    ').split('\n')
                                 if line.strip()])
            return ref

        @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                                in_signature='s', out_signature='a{sv}')  # noqa: flake8
        def GetAll(self, iface_name):
            properties = self._get_class_properties()
            results = {}
            for name, property in properties.get(iface_name, {}).items():
                results[name] = property.fget(self)
            if results:
                return results
            else:
                raise self.ServiceOnboardException(
                    'Unknown interface \'{0}\''.format(iface_name))

        @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                                in_signature='ss', out_signature='v')  # noqa: flake8
        def Get(self, iface_name, prop_name):
            prop = self._get_property(iface_name, prop_name)

            if not prop.fget:
                raise self.ServiceOnboardException(
                    ('Property not readable \'{0}\'').format(prop_name))

            return prop.fget(self)

        @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                                in_signature='ssv')  # noqa: flake8
        def Set(self, iface_name, prop_name, value):
            prop = self._get_property(iface_name, prop_name)

            if not prop.fset:
                raise self.ServiceOnboardException(
                    ('Property not writable \'{0}\'').format(prop_name))

            prop.fset(self, value)

        @dbus.service.signal(dbus_interface=dbus.PROPERTIES_IFACE,
                             signature='sa{sv}as')  # noqa: flake8
        def PropertiesChanged(self, iface, changed, invalidated):
            return iface, changed, invalidated

