/*
 * Copyright © 2016 marmuta <marmvta@gmail.com>
 * Copyright © 2016 Simon Schumann
 *
 * DBus proxy and default keyboard hiding based on ideas by Simon Schumann.
 * https://github.com/schuhumi/gnome-shell-extension-onboard-integration
 *
 * EdgeDragAction gesture based on code by Simon Schumann.
 * https://github.com/schuhumi/gnome-shell-extension-slide-for-keyboard
 *
 * This file is part of Onboard.
 *
 * Onboard is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.

 * Onboard is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <http://www.gnu.org/licenses/>.
 */

const Clutter = imports.gi.Clutter;
const St = imports.gi.St;
const Main = imports.ui.main;
const Tweener = imports.ui.tweener;
const Keyboard = imports.ui.keyboard.Keyboard;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Lang = imports.lang;
const Shell = imports.gi.Shell;
const EdgeDragAction = imports.ui.edgeDragAction;

const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;

const this_extension = imports.misc.extensionUtils.getCurrentExtension();
const Convenience = this_extension.imports.convenience;

let _onboard;
let _indicator;
let _gesture = null;
let Schema;


const OnboardIndicator = new Lang.Class({
    Name: 'OnboardIndicator',
    Extends: PanelMenu.Button,

    _init: function() {
        this.parent(0.0, _('Onboard'));

        this._last_event_time = 0;

        this._hbox = new St.BoxLayout({ style_class: 'panel-status-menu-box' });
        this._hbox.add_child(new St.Icon({icon_name: 'onboard-panel',
                                          style_class: 'system-status-icon',
                                         }));
        this.actor.add_child(this._hbox);

        this.menu.addAction(_('Preferences'), function(event) {
            GLib.spawn_command_line_async('onboard-settings', null);
        });

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this.menu.addAction(_('Help'), function(event) {
            GLib.spawn_command_line_async('/usr/bin/yelp help:onboard', null);
        });
    },

    _onEvent: function(actor, event) {
        if (event.type() == Clutter.EventType.TOUCH_BEGIN ||
            event.type() == Clutter.EventType.BUTTON_PRESS &&
            event.get_button() == 1)
        {
            // TOUCH_BEGIN and BUTTON_PRESS may come together.
            // Act only on the first one.
            if (event.get_time() - this._last_event_time > 500) {
                _onboard.launch(); // make sure it's running
                _onboard.ToggleVisible();
                this._last_event_time = event.get_time();
            }
            return Clutter.EVENT_PROPAGATE;
        }
        else
            return this.parent(actor, event);
    },

    _onPreferencesActivate: function(item) {
    },

    destroy: function() {
        this.parent();
    },
});


const Onboard = new Lang.Class({
    Name: 'Onboard',

    _init: function() {
        const IOnboardKeyboard = '<node> \
          <interface name="org.onboard.Onboard.Keyboard"> \
            <method name="ToggleVisible"> \
            </method> \
            <method name="Show"> \
            </method> \
            <method name="Hide"> \
            </method> \
          </interface> \
        </node>';

        const OnboardProxy = Gio.DBusProxy.makeProxyWrapper(IOnboardKeyboard);
        this.proxy = new OnboardProxy(Gio.DBus.session,
                                      'org.onboard.Onboard',
                                      '/org/onboard/Onboard/Keyboard');
        this._oldKeyboardShow = null;
        this._oldKeyboardHide = null;
    },

    enable: function() {
        // Start Onboard to overcome --not-show-in=GNOME
        // in onboard-autostart.desktop.
        this.launch();

        function KeyboardShow(outer_this) {
            return (function(monitor) {
                if (!this._keyboardRequested)
                    return;

                Main.layoutManager.keyboardIndex = monitor;

                // In the normal desktop?
                if (Main.actionMode == Shell.ActionMode.NORMAL)
                {
                    // Keep built-in keyboard hidden
                    this._hideSubkeys();
                    Main.layoutManager.hideKeyboard();
                    this._keyboardVisible = true;
                }
                // In overview or modal (password) dialog
                else
                {
                    // hide Onboard
                    outer_this.Hide();

                    // Show built-in keyboard
                    this._redraw();
                    Main.layoutManager.showKeyboard();
                }
                this._destroySource();
            });
        };

        function KeyboardHide(outer_this) {
            return (function() {
                if (this._keyboardRequested)
                    return;

                // still keep default keyboard hidden
                this._hideSubkeys();
                Main.layoutManager.hideKeyboard();
                this._createSource();
            });
        };

        this._oldKeyboardShow = Keyboard.prototype['_show'];
        this._oldKeyboardHide = Keyboard.prototype['_hide'];
        Keyboard.prototype['_show'] = KeyboardShow(this);
        Keyboard.prototype['_hide'] = KeyboardHide(this);
    },

    disable: function() {
        Keyboard.prototype['_show'] = this._oldKeyboardShow;
        Keyboard.prototype['_hide'] = this._oldKeyboardHide;

        // Kill Onboard
        GLib.spawn_command_line_async('killall onboard', null);
    },

    // Show on user request - either Onboard or the built-in keyboard.
    ShowAnyKeyboard: function() {
        // Show built-in keyboard where appropriate. Won't show Onboard
        // because it uses its own auto-show.
        Main.keyboard._keyboardRequested = true;
        Main.keyboard._keyboardVisible = false;
        Main.keyboard.Show(global.get_current_time());

        // Show Onboard
        if (Main.actionMode == Shell.ActionMode.NORMAL)
        {
            this.Show();
        }
    },

    launch: function() {
        if (!this.proxy.g_name_owner)  // not yet running?
            GLib.spawn_command_line_async('onboard', null);
    },
    Show: function() {
        this.proxy.ShowSync();
    },
    Hide: function() {
        this.proxy.HideSync();
    },
    ToggleVisible: function() {
        this.proxy.ToggleVisibleRemote();
    },
});

function enable_show_gesture(enable) {
    if (enable)
    {
        if (_gesture == null)
        {
            _gesture = new EdgeDragAction.EdgeDragAction(
                    St.Side.BOTTOM, Shell.ActionMode.NORMAL);
            _gesture.connect('activated', Lang.bind(this, function() {
                _onboard.ShowAnyKeyboard();
            }));
            global.stage.add_action(_gesture);
        }
    }
    else
    {
        if (_gesture != null)
        {
            global.stage.remove_action(_gesture);
            _gesture = null;
        }
    }
}

function update_show_gesture(dummy) {
    let enable = Schema.get_boolean('enable-show-gesture');
    enable_show_gesture(enable);
}

function init() {
    Convenience.initTranslations();
    Schema = Convenience.getSettings();
}

function enable() {
    // Update schema-version
    let schema_version = Schema.get_string('schema-version');
    if (!schema_version) {
        Schema.set_string('schema-version', '1.0');

        // enable auto-show on first start
        let auto_show = new Gio.Settings({schema_id: 'org.onboard.auto-show'});
        if (auto_show)
            auto_show.set_boolean('enabled', true);
    }

    _onboard = new Onboard();
    _onboard.enable();

    Main.onboard = _onboard;   // debug
    _onboard.Schema = Schema;

    _indicator = new OnboardIndicator();
    Main.panel.addToStatusArea('onboard-menu', _indicator);

    update_show_gesture();

    Schema.connect('changed::enable-show-gesture', update_show_gesture);
}

function disable() {
    //Schema.disconnect(enable_show_gesture);
    enable_show_gesture(false);
    _onboard.disable();
    _onboard = null;
    _indicator.destroy();
     Schema.run_dispose();
}

