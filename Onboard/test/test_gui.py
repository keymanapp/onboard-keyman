#!/usr/bin/python3

# Copyright © 2015-2017 marmuta <marmvta@gmail.com>
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

import os
import sys
import time
import tempfile
import re
import subprocess
import threading
import unittest
from contextlib import contextmanager, ExitStack

import dbus
from dbus.mainloop.glib import DBusGMainLoop

from Onboard.Version import require_gi_versions
require_gi_versions()
from gi.repository import GLib, Gtk

from Onboard.utils import Rect
from Onboard.LanguageSupport import LanguageDB
from Onboard.definitions import Handle


DBUS_NAME = "org.onboard.Onboard"
DBUS_PATH  = "/org/onboard/Onboard/Keyboard"
DBUS_IFACE = "org.onboard.Onboard.Keyboard"


class _TestGUIBase(unittest.TestCase):

    class OnboardRemoteInstance:
        def __init__(self, p, bus):
            self.process = p
            self._bus = bus
            self._keyboard = None
            self._keys = []

        def get_keyboard(self):
            if self._keyboard is None:
                proxy = self._bus.get_object(DBUS_NAME, DBUS_PATH)
                self._keyboard = dbus.Interface(proxy, DBUS_IFACE)
            return self._keyboard

        def get_keys(self):
            # if not self._keys:
            if True:  # don't lose sync when switching layers
                class Key:
                    pass
                keyboard = self.get_keyboard()
                for id, extents, labels, states in keyboard.GetKeyState():
                    key = Key()
                    key.id = id
                    key.labels = labels
                    key.screen_rect = Rect(*extents)
                    for name, value in states.items():
                        setattr(key, name, value)
                    self._keys.append(key)

            return self._keys

        def char_to_key_id(self, char):
            if char == " ":
                return "SPCE"
            for key in self.get_keys():
                if char in key.labels.values():
                    return key.id
            else:
                raise ValueError("unknown character '{}'".format(char))
            return ""

        def get_key(self, key_id):
            """ Center of key in screen coordinates """
            for key in self.get_keys():
                if key.id == key_id:
                    return key
            else:
                raise ValueError("unknown key_id '{}'".format(key_id))
            return None

        def get_key_center(self, key_id):
            """ Center of key in screen coordinates """
            key = self.get_key(key_id)
            x, y = key.screen_rect.get_center()
            return int(x), int(y)

    class TextWindow:
        """ Little window with a text entry to capture Onboard's typing in."""

        def __init__(self):
            self.loop = GLib.MainLoop()
            self.win = Gtk.Window(default_height=50, default_width=300)
            self.win.connect("delete-event", lambda *x: self.loop.quit())
            self.entry = Gtk.Entry()
            self.win.add(self.entry)
            self.win.show_all()
            self._running = True
            self.process_events()
            #threading.Thread(target=self.run_loop).start()

        def close(self):
            text = self.entry.get_text()
            self.process_events()
            self.loop.quit()
            self.process_events()
            self._running = False
            self.win.destroy()
            self.process_events()
            return text

        def process_events(self):
            while self.loop.get_context().iteration(False):
                pass

        def run_loop(self):
            while self._running:
                self.loop.get_context().iteration()

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="test_onboard_")
        self._dir = self._tmp_dir.name
        self._user_dir = os.path.join(self._dir, "onboard")
        self._model_dir = os.path.join(self._user_dir, "models")

        # setup a fresh dconf database
        self._dconf_db_name = "_onboard_test_db"
        self._dconf_db_fn = os.path.join(self.get_config_home(),
                                         "dconf", self._dconf_db_name)
        self._dconf_profile_fn = os.path.join(self._dir, "dconf_profile")
        self._write_file(self._dconf_profile_fn,
                         ["user-db:" + self._dconf_db_name])
        self._dconf_reset()  # clear everything

        self._bus = dbus.SessionBus(mainloop=DBusGMainLoop())

    def tearDown(self):
        os.remove(self._dconf_db_fn)
        self._tmp_dir.cleanup()

    def assertRectInRange(self, r_result, r_expect, tolerance=0):
        for attr in Rect.attributes:
            with self.subTest(attribute=attr):
                expected = getattr(r_expect, attr)
                result = getattr(r_result, attr)
                self.assertInRange(result,
                                   expected - tolerance,
                                   expected + tolerance,
                                   "Rect." + attr)

    def assertInRange(self, value, begin, end, variable):
        self.assertTrue(begin <= value <= end,
                    "{}={} not in range {}..{}"
                    .format(variable, value, begin, end))

    def _key_center(self, rwin, key_id):
        frame = 5
        rkb = rwin.copy()

        # word suggestion row visible?
        if self._gsettings_get(
                "org.onboard.typing-assistance.word-suggestions", "enabled"):
            hws = (rwin.h - 2 * frame) / 6
            rkb.y += hws
            rkb.h -= hws

        h_key = (rkb.h - 2 * frame) / 5
        w_key = h_key

        if key_id == "move":
            x = rkb.right() - w_key / 2
            y = rkb.y + frame + 1.5 * h_key

        if key_id == "layer1":
            x = rkb.right() - w_key / 2
            y = rkb.y + frame + 3.5 * h_key

        if key_id == "NMLK":
            x = rkb.x + rkb.w * 0.7
            y = rkb.y + frame + 0.5 * h_key

        return int(x), int(y)

    def _get_window_rect(self):
        return self._get_window_landscape_rect()

    def _set_window_rect(self, r):
        self._set_window_landscape_rect(r)

    def _get_window_landscape_rect(self):
        return Rect(
            self._gsettings_get("org.onboard.window.landscape", "x"),
            self._gsettings_get("org.onboard.window.landscape", "y"),
            self._gsettings_get("org.onboard.window.landscape", "width"),
            self._gsettings_get("org.onboard.window.landscape", "height"))

    def _set_window_landscape_rect(self, r):
        self._gsettings_set("org.onboard.window.landscape", "x", r.x)
        self._gsettings_set("org.onboard.window.landscape", "y", r.y)
        self._gsettings_set("org.onboard.window.landscape", "width", r.w)
        self._gsettings_set("org.onboard.window.landscape", "height", r.h)

    def _get_window_portrait_rect(self):
        return Rect(
            self._gsettings_get("org.onboard.window.portrait", "x"),
            self._gsettings_get("org.onboard.window.portrait", "y"),
            self._gsettings_get("org.onboard.window.portrait", "width"),
            self._gsettings_get("org.onboard.window.portrait", "height"))

    def _set_window_portrait_rect(self, r):
        self._gsettings_set("org.onboard.window.portrait", "x", r.x)
        self._gsettings_set("org.onboard.window.portrait", "y", r.y)
        self._gsettings_set("org.onboard.window.portrait", "width", r.w)
        self._gsettings_set("org.onboard.window.portrait", "height", r.h)

    def _get_icon_palette_rect(self):
        return self._get_icon_palette_landscape_rect()

    def _set_icon_palette_rect(self, r):
        self._set_window_landscape_rect(r)

    def _get_icon_palette_landscape_rect(self):
        schema = "org.onboard.icon-palette.landscape"
        return Rect(
            self._gsettings_get(schema, "x"),
            self._gsettings_get(schema, "y"),
            self._gsettings_get(schema, "width"),
            self._gsettings_get(schema, "height"))

    def _set_icon_palette_landscape_rect(self, r):
        schema = "org.onboard.icon-palette.landscape"
        self._gsettings_set(schema, "x", r.x)
        self._gsettings_set(schema, "y", r.y)
        self._gsettings_set(schema, "width", r.w)
        self._gsettings_set(schema, "height", r.h)

    def _get_icon_palette_portrait_rect(self):
        schema = "org.onboard.icon-palette.portrait"
        return Rect(
            self._gsettings_get(schema, "x"),
            self._gsettings_get(schema, "y"),
            self._gsettings_get(schema, "width"),
            self._gsettings_get(schema, "height"))

    def _set_icon_palette_portrait_rect(self, r):
        schema = "org.onboard.icon-palette.portrait"
        self._gsettings_set(schema, "x", r.x)
        self._gsettings_set(schema, "y", r.y)
        self._gsettings_set(schema, "width", r.w)
        self._gsettings_set(schema, "height", r.h)

    def _enable_major_features(self, auto_show=True):
        # turn major features on
        self._gsettings_set("org.onboard.auto-show", "enabled", auto_show)
        self._gsettings_set("org.onboard.typing-assistance.word-suggestions",
                            "enabled", True)
        self._gsettings_set("org.onboard.icon-palette", "in-use", True)

        # no dialog on startup
        self._gsettings_set("org.gnome.desktop.interface",
                            "toolkit-accessibility", True)
    def _use_system_defaults(self, use):
        self._gsettings_set("org.onboard", "use-system-defaults", use)


    def _mouse_sweep(self, x0, y0, x1, y1, step=5):
        xd = x1 - x0
        yd = y1 - y0
        n = int(max(abs(xd), abs(yd)) / step)
        for i in range(n):
            x = x0 + xd * i / (n - 1)
            y = y0 + yd * i / (n - 1)
            self._xte("mousemove", int(x), int(y))
            # time.sleep(0.1)

        # The last motion event seems to be only sent for the core
        # pointer device. -> Trigger a redundant motion event with the last
        # position to make sure there is an event coming from the XTest
        # slave device too. Else handles won't move all the way in the
        # move/resize tests.
        self._xte("mousemove", int(x1), int(y1))

    def _click_string(self, remote_instance, s):
        for c in s:
            key_id = remote_instance.char_to_key_id(c)
            x, y = remote_instance.get_key_center(key_id)
            self._xte("mousemove", x, y)
            self._xte("mouseclick", 1)
            time.sleep(0.3)

    def _click_key(self, remote_instance, key_id):
        x, y = remote_instance.get_key_center(key_id)
        self._xte("mousemove", x, y)
        self._xte("mouseclick", 1)
        time.sleep(0.3)

    @contextmanager
    def _run_onboard(self, params=[], env={},
                     capture_output=False, print_output=False):
        with self._run_onboard_script("./onboard", params, env,
                                      capture_output, print_output) as p:
            self._wait_name_owner_changed(self._bus, DBUS_NAME)
            time.sleep(1)
            instance = self.OnboardRemoteInstance(p, self._bus)
            yield instance
            p.terminate()

    @contextmanager
    def _run_onboard_settings(self, params=[], env={},
                              capture_output=False, print_output=False,
                              delay=2.0):
        with self._run_onboard_script("./onboard-settings",
                                      params, env,
                                      capture_output, print_output) as p:
            time.sleep(delay)
            yield p
            p.terminate()
            # self._xte("key", "Escape")

    @contextmanager
    def _run_onboard_script(self, command, params=[], _env={},
                            capture_output=False, print_output=False):
        try:
            env = dict(os.environ)
            env["DCONF_PROFILE"] = self._dconf_profile_fn
            env["XDG_DATA_HOME"] = self._dir
            env["LANG"] = "en_US.UTF-8"
            env.update(_env)

            cmd_line = [command]
            if params:
                cmd_line += params

            if capture_output:
                stdout_opt = subprocess.PIPE
                stderr_opt = subprocess.PIPE
            elif print_output:
                stdout_opt = subprocess.PIPE
                stderr_opt = subprocess.STDOUT
            else:
                stdout_opt = None
                stderr_opt = None

            p = subprocess.Popen(cmd_line, env=env,
                                 stdout=stdout_opt,
                                 stderr=stderr_opt,
                                 close_fds=True,
                                 universal_newlines=True,
                                 )
            yield p

        finally:
            if capture_output:
                p.stdout_lines = [line.replace("\n", "") for line in p.stdout]
                p.stderr_lines = [line.replace("\n", "") for line in p.stderr]

                # prevent ResourceWarning:
                # unclosed file <_io.BufferedReader name=12> testMethod()
                p.stderr.close()
                p.stdout.close()

            elif print_output:
                # filter out annoying Gtk deprecation warnings
                # we cannot remove yet
                blacklist = [
                    "is deprecated and shouldn't be used anymore",
                    "builder.add_from_file",
                    "GtkDialog mapped without a transient parent",
                ]
                for line in p.stdout:
                    line = line.replace("\n", "")
                    if line and \
                       not any(s in line for s in blacklist):
                        print("stderr:", line, file=sys.stderr)

                # prevent ResourceWarning:
                # unclosed file <_io.BufferedReader name=12> testMethod()
                p.stdout.close()

    def _system_gsettings_set(self, schema, key, value):
        self._gsettings_set_with_env(schema, key, value, None)

    def _gsettings_set(self, schema, key, value):
        env = dict(os.environ)
        env["DCONF_PROFILE"] = self._dconf_profile_fn
        env["LANG"] = "en_US.UTF-8"
        self._gsettings_set_with_env(schema, key, value, env)

    def _gsettings_set_with_env(self, schema, key, value, env):
        if value is True:
            valstr = "true"
        elif value is False:
            valstr = "false"
        else:
            valstr = str(value)

        p = subprocess.Popen(["gsettings", "set",
                              schema, key, valstr], env=env)
        p.wait()

    def _system_gsettings_get(self, schema, key):
        return self._gsettings_get_with_env(schema, key, None)

    def _gsettings_get(self, schema, key):
        env = dict(os.environ)
        env["DCONF_PROFILE"] = self._dconf_profile_fn
        env["LANG"] = "en_US.UTF-8"
        return self._gsettings_get_with_env(schema, key, env)

    def _gsettings_get_with_env(self, schema, key, env):
        valstr = subprocess.check_output(["gsettings", "get",
                                         schema, key], env=env)
        valstr = valstr.decode("UTF-8").replace("\n", "")
        if valstr == "true":
            value = True
        elif valstr == "false":
            value = False
        else:
            try:
                value = int(valstr)
            except ValueError:
                try:
                    value = float(valstr)
                except ValueError:
                    value = valstr
        return value

    def _dconf_reset(self):
        env = dict(os.environ)
        env["DCONF_PROFILE"] = self._dconf_profile_fn
        env["LANG"] = "en_US.UTF-8"
        subprocess.check_call(["dconf", "reset", "-f", "/"], env=env)

    def _xte(self, *params):
        env = dict(os.environ)
        env["LANG"] = "en_US.UTF-8"
        command = ["xte", " ".join(str(p) for p in params)]
        # print(command, file=sys.stderr)
        subprocess.check_call(command, env=env)

    def _get_numlock_state(self):
        output = subprocess.check_output(["numlockx", "status"]).decode()
        if " off" in output:
            return False
        elif " on" in output:
            return True
        else:
            self.assertTrue(False)
        return None

    def _set_numlock_state(self, on):
        subprocess.check_call(["numlockx", "on" if on else "off"])

    def _rotate_screen(self, rotation):
        output = subprocess.check_output(
            ['/bin/bash', '-c', 'xrandr | grep primary | cut -d" " -f1'])
        output = output.decode().replace("\n", "")
        if rotation == "landscape":
            subprocess.check_call(
                ['xrandr', "--output", output, "--rotate", "normal"])
        elif rotation == "portrait":
            subprocess.check_call(
                ['xrandr', "--output", output, "--rotate", "left"])

    @staticmethod
    def _wait_name_owner_changed(bus, name):

        def on_name_owner_changed(name, old, new):
            if not old:
                loop.quit()

        bus.add_signal_receiver(on_name_owner_changed,
                                "NameOwnerChanged",
                                dbus.BUS_DAEMON_IFACE,
                                arg0=name)
        loop = GLib.MainLoop()
        loop.run()

    @staticmethod
    def get_config_home(file=None):
        """
        User specific config directory.
        """
        path = os.environ.get("XDG_CONFIG_HOME")
        if path and not os.path.isabs(path):
            path = None

        if not path:
            path = os.path.join(os.path.expanduser("~"), ".config")

        if file:
            path = os.path.join(path, file)

        return path

    @staticmethod
    def _write_file(fn, lines):
        with open(fn, mode="w", encoding="UTF-8") as f:
            for l in lines:
                f.write(l)

    @staticmethod
    def _touch(fn, size):
        with open(fn, mode="w") as f:
            if size:
                f.write("*" * size)


class TestWindowHandling(_TestGUIBase):

    def test_keyboard_moving_remembered_after_restart(self):
        self._disable_docking()

        r = self._get_window_rect()
        dx = 100
        dy = 200
        with self._run_onboard():
            x, y = self._key_center(r, "move")
            self._xte("mousemove", x, y)
            self._xte("mousedown", 1)
            time.sleep(0.5)
            self._mouse_sweep(x, y, x + dx, y + dy)
            time.sleep(0.5)
            self._xte("mouseup", 1)
            time.sleep(0.5)

        k = 20  # ignore a few lost pixels due to drag threshold and xte moving
        r_expect = r.offset(dx, dy)
        r_result = self._get_window_rect()
        self.assertEqual(r_expect.get_size(), r_result.get_size())
        self.assertTrue(r_expect.x - k <= r_result.x <= r_expect.x,
                        "expected={} result={}".format(r_expect.x, r_result.x))
        self.assertTrue(r_expect.y - k <= r_result.y <= r_expect.y,
                        "expected={} result={}".format(r_expect.y, r_result.y))

        # rect must not change after next restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_window_rect()))

        # rect must not change after another restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_window_rect()))

    def test_keyboard_resizing_remembered_after_restart(self):
        self._disable_docking()

        r = self._get_window_rect()
        dx = 100
        dy = 200
        dx_handle = 5
        dy_handle = 5
        with self._run_onboard():
            x, y = r.right() - dx_handle, r.bottom() - dy_handle
            self._xte("mousemove", x, y)
            self._xte("mousedown", 1)
            time.sleep(0.5)
            self._mouse_sweep(x, y, x + dx, y + dy)
            time.sleep(0.5)
            self._xte("mouseup", 1)
            time.sleep(0.5)

        k = 20  # ignore a few lost pixels due to drag threshold and xte moving
        r_expect = r.copy()
        r_expect.w = r.w + dx
        r_expect.h = r.h + dy
        r_result = self._get_window_rect()

        self.assertEqual(r_expect.left_top(), r_result.left_top())
        self.assertTrue(r_expect.w - k <= r_result.w <= r_expect.w,
                        "expected={} result={}".format(r_expect.w, r_result.w))
        self.assertTrue(r_expect.h - k <= r_result.h <= r_expect.h,
                        "expected={} result={}".format(r_expect.h, r_result.h))

        # rect must not change after next restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_window_rect()))

        # rect must not change after another restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_window_rect()))

    def test_icon_palette_moving_remembered_after_restart(self):
        self._gsettings_set("org.onboard", "start-minimized", True)
        self._gsettings_set("org.onboard.icon-palette", "in-use", True)

        r = self._get_icon_palette_rect()
        dx = 100
        dy = 200
        with self._run_onboard():
            x, y = (int(val) for val in r.get_center())
            self._xte("mousemove", x, y)
            self._xte("mousedown", 1)
            time.sleep(0.5)
            self._mouse_sweep(x, y, x + dx, y + dy)
            time.sleep(0.5)
            self._xte("mouseup", 1)
            time.sleep(0.5)

        k = 10  # ignore a few lost pixels due to drag threshold and xte moving
        r_expect = r.offset(dx, dy)
        r_result = self._get_icon_palette_rect()
        self.assertEqual(r_expect.get_size(), r_result.get_size())
        self.assertTrue(r_expect.x - k <= r_result.x <= r_expect.x,
                        "expected={} result={}".format(r_expect.x, r_result.x))
        self.assertTrue(r_expect.y - k <= r_result.y <= r_expect.y,
                        "expected={} result={}".format(r_expect.y, r_result.y))

        # rect must not change after next restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_icon_palette_rect()))

        # rect must not change after another restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_icon_palette_rect()))

    def test_icon_palette_resizing_remembered_after_restart(self):
        self._gsettings_set("org.onboard", "start-minimized", True)
        self._gsettings_set("org.onboard.icon-palette", "in-use", True)

        r = self._get_icon_palette_rect()
        dx = 100
        dy = 200
        dx_handle = 5
        dy_handle = 5
        with self._run_onboard():
            x, y = r.right() - dx_handle, r.bottom() - dy_handle
            self._xte("mousemove", x, y)
            self._xte("mousedown", 1)
            time.sleep(0.5)
            self._mouse_sweep(x, y, x + dx, y + dy)
            time.sleep(0.5)
            self._xte("mouseup", 1)
            time.sleep(0.5)

        k = 10  # ignore a few lost pixels due to drag threshold and xte moving
        r_expect = r.copy()
        r_expect.w = r.w + dx
        r_expect.h = r.h + dy
        r_result = self._get_icon_palette_rect()

        self.assertEqual(r_expect.left_top(), r_result.left_top())
        self.assertTrue(r_expect.w - k <= r_result.w <= r_expect.w,
                        "expected={} result={}".format(r_expect.w, r_result.w))
        self.assertTrue(r_expect.h - k <= r_result.h <= r_expect.h,
                        "expected={} result={}".format(r_expect.h, r_result.h))

        # rect must not change after next restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_icon_palette_rect()))

        # rect must not change after another restart
        with self._run_onboard():
            pass
        self.assertEqual(str(r_result), str(self._get_icon_palette_rect()))

    @unittest.skip("unfinished")
    def test_screen_rotation(self):
        self._enable_major_features()
        self._gsettings_set("org.onboard.icon-palette", "in-use", True)
        self._gsettings_set("org.onboard.icon-palette.landscape", "x", 600)
        self._gsettings_set("org.onboard.icon-palette.landscape", "y", 200)
        self._gsettings_set("org.onboard.window.landscape", "x", 200)
        self._gsettings_set("org.onboard.window.landscape", "y", 300)

        self._gsettings_set("org.onboard.window.portrait", "x", 200)
        self._gsettings_set("org.onboard.window.portrait", "y", 600)

        self._rotate_screen("landscape")

        dx = 100
        dy = 100
        tolerance = 15
        r_before_landscape = self._get_window_landscape_rect()
        r_before_portrait = self._get_window_portrait_rect()
        with self._run_onboard():
            self._move_handle_rel(Handle.NORTH_WEST, r_before_landscape,
                                  dx, dy)
            self._move_handle_rel(Handle.SOUTH_EAST, r_before_landscape,
                                  dx, dy)
            time.sleep(1.0)

            self._rotate_screen("portrait")
            time.sleep(5)

            self._move_handle_rel(Handle.NORTH_WEST, r_before_portrait, dx, dy)
            self._move_handle_rel(Handle.SOUTH_EAST, r_before_portrait, dx, dy)
            time.sleep(1.0)

            self._rotate_screen("landscape")
            time.sleep(5)

        time.sleep(0.5)

        # print (r, file=sys.stderr)
        # print (r.inflate(dx, dy), file=sys.stderr)
        # print (self._get_window_landscape_rect(), file=sys.stderr)
        self.assertRectInRange(self._get_window_landscape_rect(),
                               r_before_landscape.inflate(dx, dy), tolerance)
        self.assertRectInRange(self._get_window_portrait_rect(),
                               r_before_portrait.inflate(dx, dy), tolerance)

    def test_icon_palette_resizing(self):
        self._gsettings_set("org.onboard", "start-minimized", True)
        self._gsettings_set("org.onboard.icon-palette", "in-use", True)
        self._gsettings_set("org.onboard.icon-palette.landscape", "x", 300)
        self._gsettings_set("org.onboard.icon-palette.landscape", "y", 300)
        self._test_window_resizing(self._get_icon_palette_rect,
                                   self._set_icon_palette_rect)

    def test_keyboard_window_resizing(self):
        self._disable_docking()

        self._gsettings_set("org.onboard.window.landscape", "x", 300)
        self._gsettings_set("org.onboard.window.landscape", "y", 300)
        self._test_window_resizing(self._get_window_rect,
                                   self._set_window_rect)

    def _test_window_resizing(self, get_window_rect, set_window_rect):
        dx = 100
        dy = 100
        tolerance = 15  # there's some loss due to drag-threshold and others
        r_default = get_window_rect()

        with self.subTest(comment="corners1"):
            set_window_rect(r_default)

            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.NORTH_WEST, r, dx, dy)
                self._move_handle_rel(Handle.SOUTH_EAST, r, dx, dy)

            self.assertRectInRange(get_window_rect(),
                                r.inflate(dx, dy), tolerance)

            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.NORTH_WEST, r, -dx, -dy)
                self._move_handle_rel(Handle.SOUTH_EAST, r, -dx, -dy)

            self.assertRectInRange(get_window_rect(),
                                r.deflate(dx, dy), tolerance)

        with self.subTest(comment="corners2"):
            set_window_rect(r_default)

            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.SOUTH_WEST, r, dx, dy)
                self._move_handle_rel(Handle.NORTH_EAST, r, dx, dy)

            self.assertRectInRange(get_window_rect(),
                                r.inflate(dx, dy), tolerance)

            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.SOUTH_WEST, r, -dx, -dy)
                self._move_handle_rel(Handle.NORTH_EAST, r, -dx, -dy)

            self.assertRectInRange(get_window_rect(),
                                r.deflate(dx, dy), tolerance)

        with self.subTest(comment="edges"):
            set_window_rect(r_default)
            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.NORTH, r, dx, dy)
                self._move_handle_rel(Handle.EAST, r, dx, dy)
                self._move_handle_rel(Handle.SOUTH, r, dx, dy)
                self._move_handle_rel(Handle.WEST, r, dx, dy)

            self.assertRectInRange(get_window_rect(),
                                r.inflate(dx, dy), tolerance)

            r = get_window_rect()
            with self._run_onboard():
                self._move_handle_rel(Handle.NORTH, r, -dx, -dy)
                self._move_handle_rel(Handle.EAST, r, -dx, -dy)
                self._move_handle_rel(Handle.SOUTH, r, -dx, -dy)
                self._move_handle_rel(Handle.WEST, r, -dx, -dy)

            self.assertRectInRange(get_window_rect(),
                                r.deflate(dx, dy), tolerance)

    def _move_handle_rel(self, handle, r, dx, dy):
        x0, y0, x1, y1 = self._get_handle_move_vector(handle, r, dx, dy)
        self._xte("mousemove", x0, y0)
        self._xte("mousedown", 1)
        time.sleep(0.3)
        self._mouse_sweep(x0, y0, x1, y1)
        self._xte("mouseup", 1)
        time.sleep(0.3)

    def _get_handle_move_vector(self, handle, r, dx, dy):
        handle_offset = 4
        if handle in [Handle.NORTH,
                      Handle.NORTH_WEST,
                      Handle.NORTH_EAST]:
            y0 = r.y + handle_offset
            y1 = y0 - dy
        if handle in [Handle.WEST,
                      Handle.NORTH_WEST,
                      Handle.SOUTH_WEST]:
            x0 = r.x + handle_offset
            x1 = x0 - dx
        if handle in [Handle.EAST,
                      Handle.NORTH_EAST,
                      Handle.SOUTH_EAST]:
            x0 = r.right() - handle_offset
            x1 = x0 + dx
        if handle in [Handle.SOUTH,
                      Handle.SOUTH_WEST,
                      Handle.SOUTH_EAST]:
            y0 = r.bottom() - handle_offset
            y1 = y0 + dy

        if handle in [Handle.NORTH,
                      Handle.SOUTH]:
            x0 = int(r.get_center()[0])
            x1 = x0
        if handle in [Handle.WEST,
                      Handle.EAST]:
            y0 = int(r.get_center()[1])
            y1 = y0

        return x0, y0, x1, y1

    def _disable_docking(self):
        with self._run_onboard():   # apply system defaults -> docking enabled
            pass
        self._gsettings_set("org.onboard.window", "docking-enabled", False)


class TestKeys(_TestGUIBase):

    @unittest.skip("freezes too easily")
    def test_modifier_unlatching(self):
        tests = (
            [
                "Small",
                "[LFSH]abc ",
                "Abc "
            ],
            [
                "Compact",
                "[LFSH]abc [RTSH]def",
                "Abc Def"
            ],
            [
                "Full Keyboard",
                "[LFSH]abc [RTSH]def",
                "Abc Def"
            ],
            [
                "Phone",
                "[LFSH]abc ",
                "Abc "
            ],
            [
                "Grid",
                "[LFSH]abc ",
                "Abc "
            ],
        )

        self._enable_major_features(auto_show=False)
        self._use_system_defaults(False)

        for layout, challenge, expectation in tests:
            self._gsettings_set("org.onboard", "layout", layout)
            with self.subTest(layout=layout, challenge=challenge):
                tw = self.TextWindow()
                with self._run_onboard() as instance:
                    groups = [m.groups() for m
                              in re.finditer("(?: \[ ([^\]]*) ) |"
                                             "(?: \] ([^\[]*) )",
                                             challenge, re.VERBOSE)]
                    for key_id, text in groups:
                        if key_id:
                            self._click_key(instance, key_id)
                        else:
                            self._click_string(instance, text)
                        tw.process_events()

                text = tw.close()
                time.sleep(0.5)
                self.assertEqual(text, expectation)

    def test_numlock_state_on_exit(self):
        self._enable_major_features()

        tests = [
            [
                "NMLK off state must be preserved after exit",  # comment
                0.0,     # sticky_key_release_delay 0.0=off, !=0 = kiosk mode
                False,   # NMLK state before start
                False,   # toggle NMLK key at runtime
                False,   # NMLK state after exit
            ],
            [
                "NMLK on state must be preserved after exit",
                0.0, True, False, True,
            ],
            [
                "NMLK toggled on must still be on after exit",
                0.0, False, True, True,
            ],
            [
                "NMLK toggled off must still be off after exit",
                0.0, True, True, False,
            ],
            # Currently, if sticky_key_release_delay is != 0.0 we assume we're
            # running in a kiosk setting and reset NMLK after the delay as
            # well as on exit.
            [
                "NMLK toggled on in kiosk mode reverts to off after exit",
                5.0, False, True, False,
            ],
        ]

        old_state = self._get_numlock_state()

        for comment, skrd, active_before, toggle, active_after in tests:
            self._set_numlock_state(active_before)
            self._gsettings_set("org.onboard.keyboard",
                                "sticky-key-release-delay", skrd)

            with self._run_onboard() as instance:
                if toggle:
                    self._click_key(instance, "layer1")
                    self._click_key(instance, "NMLK")
                else:
                    time.sleep(1)

            if not toggle:  # run twice only the first two times
                with self._run_onboard():
                    time.sleep(1)

            self.assertEqual(self._get_numlock_state(), active_after, comment)

        self._set_numlock_state(old_state)


class TestMisc(_TestGUIBase):

    def test_valid_test_environment(self):
        # write to dconf database to make sure it exists
        self._gsettings_set("org.onboard", "use-system-defaults", True)
        self.assertEqual(
            self._gsettings_get("org.onboard", "use-system-defaults"),
            True)
        self.assertTrue(os.path.exists(self._dconf_db_fn))

        # database must be reset to defaults
        self.assertEqual(str(self._get_window_rect()),
                         str(Rect(100, 50, 700, 205)))

    def test_startup_with_c_locale(self):
        self._enable_major_features()

        with self._run_onboard(env={"LANG": "C"}):
            pass

        with self._run_onboard_settings(env={"LANG": "C"},
                                        print_output=True):
            pass

    @staticmethod
    def _get_languages():
        return LanguageDB.get_main_languages()

    def test_startup_with_various_languages_onboard(self):
        self._enable_major_features()

        languages = self._get_languages()
        for language in languages:
            with self.subTest(language=language):
                with self._run_onboard(env={"LANGUAGE": language}):
                    pass

    def test_startup_with_various_languages_onboard_settings(self):
        self._enable_major_features()

        languages = self._get_languages()

        # run onboard-settings for all languages
        k = 4  # max parallel languages
        for i in range(0, len(languages), k):
            langs = languages[i:i + k]
            with self.subTest(languages=langs):
                with ExitStack() as stack:
                    for language in langs:
                        stack.enter_context(
                            self._run_onboard_settings(
                                env={"LANGUAGE": language},
                                print_output=True,
                                delay=0.5))
                    time.sleep(2)

    #@unittest.skip("doesn't clean up very well")
    def test_gnome_high_contrast_themes(self):
        self._enable_major_features()

        # make sure system theme tracking is enabled, should be default
        self.assertTrue(self._gsettings_get("org.onboard",
                                            "system-theme-tracking-enabled"))

        default_gtk_theme = "Ambiance"  # default in Vivid is Adwaita?
        default_onboard_theme = "Nightshade"  # default in Vivid is Adwaita?
        # system_theme, onboard_theme
        contrast_themes = [
            ["HighContrast", "HighContrast"],                # Gtk
            ["HighContrastInverse", "HighContrastInverse"],  # Gtk
            ["LowContrast", "LowContrast"],                  # Gtk
            ["ContrastHighInverse", "HighContrastInverse"],  # MATE
        ]

        # save current gsettings state
        old_theme = self._system_gsettings_get("org.gnome.desktop.interface",
                                               "gtk-theme")

        # set normal theme for startup
        self._system_gsettings_set("org.gnome.desktop.interface",
                                   "gtk-theme", default_gtk_theme)

        # run onboard and switch through gtk-themes
        with self._run_onboard(params=["-d", "info"],
                               capture_output=True) as instance:
            time.sleep(2)
            for system_theme, onboard_theme in contrast_themes:
                self._system_gsettings_set("org.gnome.desktop.interface",
                                           "gtk-theme", system_theme)
                time.sleep(3)

            self._system_gsettings_set("org.gnome.desktop.interface",
                                       "gtk-theme", default_gtk_theme)
            time.sleep(3)

        # process debug output
        lines = [line for line in instance.process.stderr_lines
                 if "Loading theme" in line]
        self.assertEqual(len(lines), len(contrast_themes) + 2)
        self.assertIn(default_onboard_theme, lines[0])
        for i, (system_theme, onboard_theme) in enumerate(contrast_themes):
            self.assertIn(onboard_theme + ".theme", lines[i + 1])
        self.assertIn(default_onboard_theme, lines[-1])

        # undo our gsettings changes
        self._system_gsettings_set("org.gnome.desktop.interface",
                                   "gtk-theme", old_theme)

    def test_running_in_live_cd_environment(self):
        # make sure icon palatte is off (default)
        self.assertFalse(
            self._gsettings_get("org.onboard.icon-palette", "in-use"))

        # make sure status icon is on (default)
        self.assertTrue(
            self._gsettings_get("org.onboard", "show-status-icon"))

        with self._run_onboard(params=["-d", "debug"],
                               env={"RUNNING_UNDER_GDM": "1"},
                               capture_output=True) as instance:
            pass

        # preferences key must have become inaccessible
        lines = [line for line in instance.process.stderr_lines
                 if "RectKey('settings').visible" in line]
        self.assertTrue(
            len(lines) >= 1 and all("False" in line for line in lines))
        self.assertTrue(
            len(lines) >= 1 and not any("True" in line for line in lines))

        # icon palette must be on
        self.assertTrue(
            self._gsettings_get("org.onboard.icon-palette", "in-use"))

        # status icon must be off
        self.assertFalse(
            self._gsettings_get("org.onboard", "show-status-icon"))


class TestNoSetup(unittest.TestCase):

    def test_apt_cache_unmet_onboard(self):
        result = subprocess.check_output(["apt-cache", "unmet", "onboard"])
        result = result.decode("UTF-8")
        self.assertEqual(result, "")

