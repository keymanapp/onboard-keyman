/*
 * Copyright © 2016 marmuta <marmvta@gmail.com>
 *
 * DBus proxy and default keyboard hiding based on ideas by Simon Schumann.
 * https://github.com/schuhumi/gnome-shell-extension-onboard-integration
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

const Gio = imports.gi.Gio;
const Gtk = imports.gi.Gtk;
const GObject = imports.gi.GObject;
const Lang = imports.lang;

const Gettext = imports.gettext.domain('onboard');
const _ = Gettext.gettext;

const this_extension = imports.misc.extensionUtils.getCurrentExtension();
const Convenience = this_extension.imports.convenience;

let Schema;


const OnboardIndicatorWidget = new GObject.Class({
    Name: 'AlternateTab.Prefs.OnboardIndicatorWidget',
    GTypeName: 'OnboardIndicatorWidget',
    Extends: Gtk.Grid,

    _init: function(params) {
        this.parent(params);
        this.margin = 24;
        this.row_spacing = 6;
        this.orientation = Gtk.Orientation.VERTICAL;

        let check = new Gtk.CheckButton({
            label: _('Drag from bottom edge of the screen ' +
                     'to show the keyboard'),
            margin_top: 1 });
        Schema.bind('enable-show-gesture', check, 'active',
                Gio.SettingsBindFlags.DEFAULT);
        this.add(check);
    },
});

function init() {
    Convenience.initTranslations();
    Schema = Convenience.getSettings();
}

function buildPrefsWidget() {
    let widget = new OnboardIndicatorWidget();
    widget.show_all();
    return widget;
}

