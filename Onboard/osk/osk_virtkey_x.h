/*
 * Copyright © 2016 marmuta <marmvta@gmail.com>
 *
 * This file is part of Onboard.
 *
 * Onboard is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * Onboard is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef __OSK_VIRTKEY_X__
#define __OSK_VIRTKEY_X__

#include "osk_virtkey.h"

VirtkeyBase* virtkey_x_new(void);

void virtkey_x_set_group (VirtkeyBase* base, int group, bool lock);
void virtkey_x_set_modifiers (VirtkeyBase* base,
                              unsigned int mod_mask, bool lock, bool press);

#endif
