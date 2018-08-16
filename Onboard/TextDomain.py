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

import os
import re
import glob

import logging

from Onboard.Version import require_gi_versions
require_gi_versions()
try:
    from gi.repository import Atspi
except ImportError as e:
    pass

from Onboard.TextChanges  import TextSpan
from Onboard.utils        import KeyCode, Modifiers, unicode_str

_logger = logging.getLogger("TextDomain")

class TextDomains:
    """ Collection of all recognized text domains. """

    def __init__(self):
        # default domain has to be last
        self._domains = [
                         DomainTerminal(),
                         DomainURL(),
                         DomainPassword(),
                         DomainGenericText(),
                         DomainNOP()
                        ]

    def find_match(self, **kwargs):
        for domain in self._domains:
            if domain.matches(**kwargs):
                return domain
        return None  # should never happen, default domain always matches

    def get_nop_domain(self):
        return self._domains[-1]


class TextDomain:
    """
    Abstract base class as a catch-all for domain specific functionalty.
    """

    def __init__(self):
        self._url_parser = PartialURLParser()

    def matches(self, **kwargs):
        # Weed out unity text entries that report being editable but don't
        # actually provide methods of the Atspi.Text interface.
        return "Text" in kwargs.get("interfaces", [])

    def init_domain(self):
        """ Called on being selected as the currently active domain. """
        pass

    def read_context(self, keyboard, accessible):
        return NotImplementedError()

    def get_text_begin_marker(self):
        return ""

    def get_auto_separator(self, context):
        """
        Get word separator to add after inserting a prediction choice.

        Doctests:

        >>> from os.path import join

        # URL
        >>> d = DomainGenericText()
        >>> d.get_auto_separator("word http")
        ' '
        >>> d.get_auto_separator("word http://www")
        '.'
        >>> d.get_auto_separator("word http://www.domain.org/path")
        '/'
        >>> d.get_auto_separator("word http://www.domain.org/path/document.ext")
        ''

        # filename
        >>> import tempfile
        >>> from os.path import abspath, dirname, join
        >>> def touch(fn):
        ...     with open(fn, mode="w") as f: n = f.write("")
        >>> td = tempfile.TemporaryDirectory(prefix="test_onboard _")
        >>> dir = td.name

        >>> touch(join(dir, "onboard-defaults.conf.example"))
        >>> touch(join(dir, "onboard-defaults.conf.example.another"))
        >>>
        >>> d.get_auto_separator("/etc")
        '/'
        >>> d.get_auto_separator(join(dir, "onboard-defaults"))
        '.'
        >>> d.get_auto_separator(join(dir, "onboard-defaults.conf"))
        '.'
        >>> d.get_auto_separator(join(dir, "onboard-defaults.conf.example"))
        ''
        >>> d.get_auto_separator(join(dir, "onboard-defaults.conf.example.another"))
        ' '

        # filename in directory with spaces
        >>> import tempfile
        >>> td = tempfile.TemporaryDirectory(prefix="test onboard _")
        >>> dir = td.name
        >>> fn = os.path.join(dir, "onboard-defaults.conf.example")
        >>> touch(fn)
        >>> d.get_auto_separator(join(dir, "onboard-defaults"))
        '.'

        # no false positives for valid filenames before the current token
        >>> d.get_auto_separator(dir + "/onboard-defaults no-file")
        ' '
        """
        separator = " "

        # Split at whitespace to catch whole URLs/file names and
        # keep separators.
        strings = re.split('(\s+)', context)
        if strings:
            string = strings[-1]
            if self._url_parser.is_maybe_url(string):
                separator = self._url_parser.get_auto_separator(string)
            else:
                fn = self._search_valid_file_name(strings)
                if fn:
                    string = fn
                if self._url_parser._is_maybe_filename(string):
                    url = "file://" + string
                    separator = self._url_parser.get_auto_separator(url)

        return separator


    def _search_valid_file_name(self, strings):
        """
        Search for a valid filename backwards across separators.

        Doctests:
        >>> import tempfile, re, os.path
        >>>
        >>> d = DomainGenericText()
        >>>
        >>> td = tempfile.TemporaryDirectory(prefix="test onboard _")
        >>> dir = td.name
        >>> fn1 = os.path.join(dir, "file")
        >>> fn2 = os.path.join(dir, "file with many spaces")
        >>> with open(fn1, mode="w") as f: n = f.write("")
        >>> with open(fn2, mode="w") as f: n = f.write("")

        # simple file in dir with spaces must return as filename
        >>> strings = re.split('(\s+)', fn1)
        >>> "/test onboard" in d._search_valid_file_name(strings)
        True

        # file with spaces in dir with spaces must return as filename
        >>> strings = re.split('(\s+)', fn2)
        >>> "/test onboard" in d._search_valid_file_name(strings)
        True

        # random string after a valid file must not be confused with a filename
        >>> strings = re.split('(\s+)', fn2 + " no-file")
        >>> d._search_valid_file_name(strings) is None
        True
        """
        # Search backwards across spaces for an absolute filename.
        max_sections = 16  # allow this many path sections (separators+tokens)
        for i in range(min(max_sections, len(strings))):
            fn = "".join(strings[-1-i:])
            # Is it (part of) a valid absolute filename?
            # Do least impact checks first.
            if self._url_parser._is_maybe_filename(fn) and \
               os.path.isabs(fn):

                # Does a file or directory of this name exist?
                if os.path.exists(fn):
                    return fn

                # Check if it is at least an incomplete filename of
                # an existing file
                files  = glob.glob(fn + "*")
                if files:
                    return fn

        return None

    def grow_learning_span(self, text_span):
        """
        Grow span before learning to include e.g. whole URLs.

        Doctests:
        >>> d = DomainGenericText()

        # Span doesn't grow for simple words
        >>> d.grow_learning_span(TextSpan(8, 1, "word1 word2 word3"))
        (8, 1, 'r')

        # Span grows to include a complete URL
        >>> d.grow_learning_span(TextSpan(13, 1, "http://www.domain.org"))
        (0, 21, 'http://www.domain.org')

        # Span grows to include multiple complete URLs
        >>> d.grow_learning_span(TextSpan(19, 13, "http://www.domain.org word http://slashdot.org"))
        (0, 46, 'http://www.domain.org word http://slashdot.org')

        # Span grows to include a complete filename
        >>> d.grow_learning_span(TextSpan(10, 1, "word1 /usr/bin/bash word2"))
        (6, 13, '/usr/bin/bash')

        # Edge cases
        >>> d.grow_learning_span(TextSpan(6, 0, "word1 /usr/bin/bash word2"))
        (6, 0, '')
        >>> d.grow_learning_span(TextSpan(19, 0, "word1 /usr/bin/bash word2"))
        (19, 0, '')
        >>> d.grow_learning_span(TextSpan(6, 1, "word1 /usr/bin/bash word2"))
        (6, 13, '/usr/bin/bash')
        >>> d.grow_learning_span(TextSpan(18, 1, "word1 /usr/bin/bash word2"))
        (6, 13, '/usr/bin/bash')

        # Large text with text offset>0: returned position must be offset too
        >>> d.grow_learning_span(TextSpan(116, 1,
        ...     "word1 /usr/bin/bash word2", 100))
        (106, 13, '/usr/bin/bash')
        """
        text   = text_span.get_text()
        offset = text_span.text_begin()
        begin  = text_span.begin() - offset
        end    = text_span.end() - offset

        sections, spans = self._split_growth_sections(text)

        for i, s in enumerate(spans):
            if begin < s[1] and end > s[0]:  # intersects?

                section = sections[i]
                span = spans[i]
                if self._url_parser.is_maybe_url(section) or \
                   self._url_parser._is_maybe_filename(section):
                    begin = min(begin, span[0])
                    end = max(end, span[1])

        return begin + offset, end - begin, text[begin:end]

    def can_record_insertion(self, accessible, pos, length):
        return True

    def can_give_keypress_feedback(self):
        return True

    def can_spell_check(self, section_span):
        return False

    def can_auto_correct(self, section_span):
        return False

    def can_auto_punctuate(self, has_begin_of_text):
        return False

    def can_suggest_before_typing(self):
        """ Can give word suggestions before typing has started? """
        return True

    def handle_key_press(self, keycode, mod_mask):
        return True, None  # entering_text, end_of_editing

    _growth_sections_pattern = re.compile("[^\s?#@]+", re.DOTALL)

    def _split_growth_sections(self, text):
        """
        Split text at whitespace and other delimiters where
        growing learning spans should stop.

        Doctests:
        >>> d = DomainGenericText()
        >>> d._split_growth_sections("word1 www.domain.org word2. http://test")
        (['word1', 'www.domain.org', 'word2.', 'http://test'], [(0, 5), (6, 20), (21, 27), (28, 39)])

        >>> d._split_growth_sections("http://www.domain.org/?p=1#anchor")
        (['http://www.domain.org/', 'p=1', 'anchor'], [(0, 22), (23, 26), (27, 33)])

        >>> d._split_growth_sections("http://user:pass@www.domain.org")
        (['http://user:pass', 'www.domain.org'], [(0, 16), (17, 31)])
        """
        matches = self._growth_sections_pattern.finditer(text)
        tokens = []
        spans = []
        for m in matches:
            tokens.append(m.group())
            spans.append(m.span())
        return tokens, spans


class DomainNOP(TextDomain):
    """ Do-nothing domain, no focused accessible. """

    def matches(self, **kwargs):
        return True

    def read_context(self, keyboard, accessible):
        return "", "", 0, TextSpan(), False, 0

    def get_auto_separator(self, context):
        """ Get word separator to add after inserting a prediction choice. """
        return ""


class DomainPassword(DomainNOP):
    """ Do-nothing domain for password entries """

    def matches(self, **kwargs):
        return kwargs.get("role") == Atspi.Role.PASSWORD_TEXT

    def can_give_keypress_feedback(self):
        return False


class DomainGenericText(TextDomain):
    """ Default domain for generic text entry """

    def matches(self, **kwargs):
        return TextDomain.matches(self, **kwargs)

    def read_context(self, keyboard, accessible):
        """ Extract prediction context from the accessible """

        # get caret position from selection
        selection = accessible.get_selection()

        # get text around the caret position
        try:
            count = accessible.get_character_count()

            if selection is None:
                offset = accessible.get_caret_offset()

                # In Zesty, firefox 50.1 often returns caret position -1
                # when typing into the urlbar. Assume we are at the end
                # of the text when that happens.
                if offset < 0:
                    _logger.warning("DomainGenericText.read_context(): "
                                    "Atspi.Text.get_caret_offset() "
                                    "returned invalid {}. "
                                    "Pretending the cursor is at the end "
                                    "of the text at offset {}."
                                    .format(offset, count))
                    offset = count

                selection = (offset, offset)

            r = accessible.get_text_at_offset(
                selection[0], Atspi.TextBoundaryType.LINE_START)
        except Exception as ex:     # Private exception gi._glib.GError when
                                    # gedit became unresponsive.
            _logger.info("DomainGenericText.read_context(), text: " +
                         unicode_str(ex))
            return None

        line = unicode_str(r.content).replace("\n", "")
        line_caret = max(selection[0] - r.start_offset, 0)

        begin = max(selection[0] - 256, 0)
        end   = min(selection[0] + 100, count)
        try:
            text = accessible.get_text(begin, end)
        except Exception as ex:     # Private exception gi._glib.GError when
                                    # gedit became unresponsive.
            _logger.info("DomainGenericText.read_context(), text2: " +
                         unicode_str(ex))
            return None

        text = unicode_str(text)

        # Not all text may be available for large selections. We only need the
        # part before the begin of the selection/caret.
        selection_span = TextSpan(selection[0], selection[1] - selection[0],
                                  text, begin)
        context = text[:selection[0] - begin]
        begin_of_text = begin == 0
        begin_of_text_offset = 0

        return (context, line, line_caret, selection_span,
                begin_of_text, begin_of_text_offset)

    def can_spell_check(self, section_span):
        """
        Can we auto-correct this span?.

        Doctests:
        >>> d = DomainGenericText()
        >>> d.can_spell_check(TextSpan(0, 3, "abc"))
        True
        >>> d.can_spell_check(TextSpan(4, 3, "abc def"))
        True
        >>> d.can_spell_check(TextSpan(0, 20, "http://www.domain.org"))
        False
        """
        section = section_span.get_span_text()
        return not self._url_parser.is_maybe_url(section) and \
               not self._url_parser._is_maybe_filename(section)
        return True

    def can_auto_correct(self, section_span):
        """
        Can we auto-correct this span?.
        """
        return self.can_spell_check(section_span)

    def can_auto_punctuate(self, has_begin_of_text):
        return True

    def get_text_begin_marker(self):
        return "<bot:txt>"


class DomainTerminal(TextDomain):
    """ Terminal entry, in particular gnome-terminal """

    _prompt_patterns = tuple(re.compile(p, re.UNICODE) for p in
                                (
                                    "^gdb$ ",
                                    "^>>> ",              # python
                                    "^In \[[0-9]*\]: ",   # ipython
                                    "^:",                 # vi command mode
                                    "^/",                 # vi search
                                    "^\?",                # vi reverse search
                                    "\$ ",                # generic prompt
                                    "# ",                 # root prompt
                                    "^.*?@.*?/.*?> "      # fish
                                )
                            )

    _prompt_blacklist_patterns = tuple(re.compile(p, re.UNICODE) for p in
                                (
                                    "^\(.*\)`.*': ",  # bash incremental search
                                )
                            )

    def matches(self, **kwargs):
        return TextDomain.matches(self, **kwargs) and \
               kwargs.get("role") == Atspi.Role.TERMINAL

    def init_domain(self):
        pass

    def read_context(self, keyboard, accessible):
        """
        Extract prediction context from the accessible
        """
        try:
            offset = accessible.get_caret_offset()
        except Exception as ex:     # Private exception gi._glib.GError
                                    # when gedit became unresponsive.
            _logger.info("DomainTerminal.read_context(): " +
                         unicode_str(ex))
            return None

        context_lines, prompt_length, line, line_start, line_caret = \
            self._get_text_after_prompt(
                accessible, offset,
                keyboard.get_last_typed_was_separator())

        if prompt_length:
            begin_of_text = True
            begin_of_text_offset = line_start
        else:
            begin_of_text = False
            begin_of_text_offset = None

        context = "".join(context_lines)
        before_line = "".join(context_lines[:-1])
        selection_span = TextSpan(offset, 0,
                                  before_line + line,
                                  line_start - len(before_line))

        result = (context, line, line_caret, selection_span,
                  begin_of_text, begin_of_text_offset)
        return result

    def _get_text_after_prompt(self, accessible, caret_offset,
                               last_typed_was_separator=None):
        """
        Return text from the input area of the terminal after the prompt.

        Doctests:
        >>> class AtspiTextRangeMockup:
        ...     pass
        >>> class AccessibleMockup:
        ...     def __init__(self, text, width):
        ...         self._text = text
        ...         self._width = width
        ...     def get_text_at_offset(self, offset, boundary):
        ...         line = offset // self._width
        ...         lbegin = line * self._width
        ...         r = AtspiTextRangeMockup()
        ...         r.content = self._text[lbegin:lbegin+self._width]
        ...         r.start_offset = lbegin
        ...         return r
        ...     def get_text_before_offset(self, offset, boundary):
        ...         return self.get_text_at_offset(offset - self._width, boundary)
        ...     def is_byobu(self):
        ...         return False

        >>> d = DomainTerminal()

        # Single line
        >>> a = AccessibleMockup("abc$ ls /etc\\n", 15)
        >>> d._get_text_after_prompt(a, 12)
        (['ls /etc'], 5, 'ls /etc\\n', 5, 7)

        # Two lines
        >>> a = AccessibleMockup("abc$ ls /e"
        ...                      "tc\\n", 10)
        >>> d._get_text_after_prompt(a, 12)
        (['ls /e', 'tc'], 5, 'tc\\n', 10, 2)

        # Three lines: prompt not detected
        # More that two lines are not supported. The probability of detecting
        # "prompts" in random scrolling data rises with each additional line.
        >>> a = AccessibleMockup("abc$ ls /e"
        ...                      "tc/X11/xor"
        ...                      "g.conf.d\\n", 10)
        >>> d._get_text_after_prompt(a, 28)
        (['tc/X11/xor', 'g.conf.d'], 0, 'g.conf.d\\n', 20, 8)

        # Two lines with slash at the beginning of the second: detect vi
        # search prompt. Not ideal, but vi is important too.
        >>> a = AccessibleMockup("abc$ ls /etc"
        ...                      "/X11\\n", 12)
        >>> d._get_text_after_prompt(a, 16)
        (['X11'], 1, 'X11\\n', 13, 3)

        """

        r = accessible.get_text_at_offset(
            caret_offset, Atspi.TextBoundaryType.LINE_START)
        line = unicode_str(r.content)
        line_start = r.start_offset
        line_caret = caret_offset - line_start
        # remove prompt from the current or previous lines
        context_lines = []
        prompt_length = None
        l = line[:line_caret]

        # Zesty: byobu running in gnome-terminal doesn't report trailing
        # spaces in text and caret-position.
        # Awful hack: assume there is always a trailing space when the caret
        # is at the end of the line and we just typed a separator.
        if line[line_caret:] == "\n" and \
           last_typed_was_separator and \
           accessible.is_byobu():
            l += " "

        for i in range(2):

            # matching blacklisted prompt? -> cancel whole context
            if self._find_blacklisted_prompt(l):
                context_lines = []
                prompt_length = None
                break

            prompt_length = self._find_prompt(l)
            context_lines.insert(0, l[prompt_length:])
            if i == 0:
                line = line[prompt_length:]  # cut prompt from input line
                line_start += prompt_length
                line_caret -= prompt_length
            if prompt_length:
                break

            # no prompt yet -> let context reach
            # across one more line break
            r = accessible.get_text_before_offset(
                caret_offset, Atspi.TextBoundaryType.LINE_START)
            l = unicode_str(r.content)

        result = (context_lines, prompt_length,
                  line, line_start, line_caret)
        return result

    def _find_prompt(self, context):
        """
        Search for a prompt and return the offset where the user input starts.
        Until we find a better way just look for some common prompt patterns.
        """
        for pattern in self._prompt_patterns:
            match = pattern.search(context)
            if match:
                return match.end()
        return 0

    def _find_blacklisted_prompt(self, context):
        for pattern in self._prompt_blacklist_patterns:
            match = pattern.search(context)
            if match:
                return match.end()
        return None

    def get_text_begin_marker(self):
        return "<bot:term>"

    def can_record_insertion(self, accessible, offset, length):
        # Only record (for learning) when there is a known prompt in sight.
        # Problem: learning won't happen for uncommon prompts, but less random
        # junk scrolling by should enter the user model in return.
        context_lines, prompt_length, line, line_start, line_caret = \
            self._get_text_after_prompt(accessible, offset)
        return bool(prompt_length)

    def can_suggest_before_typing(self):
        """ Can give word suggestions before typing has started? """
        # Mostly prevent updates to word suggestions while text is scrolling by
        return False

    def handle_key_press(self, keycode, mod_mask):
        """
        End recording and learn when pressing [Return]
        because text that is scrolled out of view is
        lost in a terminal.
        """
        if keycode == KeyCode.Return or \
           keycode == KeyCode.KP_Enter:
            return False, True
        elif keycode == KeyCode.C and mod_mask & Modifiers.CTRL:
            return False, False

        return True, None  # entering_text, end_of_editing

    def can_auto_punctuate(self, has_begin_of_text):
        """
        Only auto-punctuate in Terminal when no prompt was detected.
        Intention is to allow punctuation assistance in editors, but disable
        it when entering commands at the prompt, e.g. for "cd ..".
        """
        return not has_begin_of_text


class DomainURL(DomainGenericText):
    """ (Firefox) address bar """

    def matches(self, **kwargs):
        return kwargs.get("is_urlbar", False)

    def get_auto_separator(self, context):
        """
        Get word separator to add after inserting a prediction choice.
        """
        return self._url_parser.get_auto_separator(context)

    def get_text_begin_marker(self):
        return "<bot:url>"

    def can_spell_check(self, section_span):
        return False


class PartialURLParser:
    """
    Parse partial URLs and predict separators.
    Parsing is neither complete nor RFC prove but probably doesn't
    have to be either. The goal is to save key strokes for the
    most common cases.

    Doctests:
    >>> p = PartialURLParser()

    >>> p.tokenize_url('http://user:pass@www.do-mai_n.nl/path/name.ext')
    ['http', '://', 'user', ':', 'pass', '@', 'www', '.', 'do-mai_n', '.', 'nl', '/', 'path', '/', 'name', '.', 'ext']

    >>> p.tokenize_url('user:pass@www.do-mai_n.nl/path/name.ext')
    ['user', ':', 'pass', '@', 'www', '.', 'do-mai_n', '.', 'nl', '/', 'path', '/', 'name', '.', 'ext']

    >>> p.tokenize_url('www.do-mai_n.nl/path/name.ext')
    ['www', '.', 'do-mai_n', '.', 'nl', '/', 'path', '/', 'name', '.', 'ext']

    >>> p.tokenize_url('www.do-mai_n.nl')
    ['www', '.', 'do-mai_n', '.', 'nl']
    """
    _gTLDs   = ["aero", "asia", "biz", "cat", "com", "coop", "info", "int",
               "jobs", "mobi", "museum", "name", "net", "org", "pro", "tel",
               "travel", "xxx"]
    _usTLDs = ["edu", "gov", "mil"]
    _ccTLDs = ["ac", "ad", "ae", "af", "ag", "ai", "al", "am", "an", "ao",
               "aq", "ar", "as", "at", "au", "aw", "ax", "az", "ba", "bb",
               "bd", "be", "bf", "bg", "bh", "bi", "bj", "bm", "bn", "bo",
               "br", "bs", "bt", "bv", "bw", "by", "bz", "ca", "cc", "cd",
               "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "co", "cr",
               "cs", "cu", "cv", "cx", "cy", "cz", "dd", "de", "dj", "dk",
               "dm", "do", "dz", "ec", "ee", "eg", "eh", "er", "es", "et",
               "eu", "fi", "fj", "fk", "fm", "fo", "fr", "ga", "gb", "gd",
               "ge", "gf", "gg", "gh", "gi", "gl", "gm", "gn", "gp", "gq",
               "gr", "gs", "gt", "gu", "gw", "gy", "hk", "hm", "hn", "hr",
               "ht", "hu", "id", "ie", "il", "im", "in", "io", "iq", "ir",
               "is", "it", "je", "jm", "jo", "jp", "ke", "kg", "kh", "ki",
               "km", "kn", "kp", "kr", "kw", "ky", "kz", "la", "lb", "lc",
               "li", "lk", "lr", "ls", "lt", "lu", "lv", "ly", "ma", "mc",
               "md", "me", "mg", "mh", "mk", "ml", "mm", "mn", "mo", "mp",
               "mq", "mr", "ms", "mt", "mu", "mv", "mw", "mx", "my", "mz",
               "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr",
               "nu", "nz", "om", "pa", "pe", "pf", "pg", "ph", "pk", "pl",
               "pm", "pn", "pr", "ps", "pt", "pw", "py", "qa", "re", "ro",
               "rs", "ru", "rw", "sa", "sb", "sc", "sd", "se", "sg", "sh",
               "si", "sj", "sk", "sl", "sm", "sn", "so", "sr", "ss", "st",
               "su", "sv", "sy", "sz", "tc", "td", "tf", "tg", "th", "tj",
               "tk", "tl", "tm", "tn", "to", "tp", "tr", "tt", "tv", "tw",
               "tz", "ua", "ug", "uk", "us", "uy", "uz", "va", "vc", "ve",
               "vg", "vi", "vn", "vu", "wf", "ws", "ye", "yt", "yu", "za",
               "zm", "zw"]
    _TLDs = frozenset(_gTLDs + _usTLDs + _ccTLDs)

    _schemes = ["http", "https", "ftp", "file"]
    _protocols = ["mailto", "apt"]
    _all_schemes = _schemes + _protocols

    _url_pattern = re.compile("([\w-]+)|(\W+)", re.UNICODE)

    def iter_url(self, url):
        return self._url_pattern.finditer(url)

    def tokenize_url(self, url):
        return[group for match in self.iter_url(url)
                     for group in match.groups() if not group is None]

    def is_maybe_url(self, context):
        """
        Is this maybe something looking like an URL?

        Doctests:
        >>> p = PartialURLParser()
        >>> p.is_maybe_url("http")
        False
        >>> p.is_maybe_url("http:")
        True
        >>> p.is_maybe_url("http://www.domain.org")
        True
        >>> p.is_maybe_url("www.domain.org")
        True
        >>> p.is_maybe_url("www.domain")
        False
        >>> p.is_maybe_url("www")
        False
        """
        tokens = self.tokenize_url(context)

        # with scheme
        if len(tokens) >= 2:
            token  = tokens[0]
            septok = tokens[1]
            if token in self._all_schemes and septok.startswith(":"):
                return True

        # without scheme
        if len(tokens) >= 5:
            if tokens[1] == "." and tokens[3] == ".":
                try:
                    index = tokens.index("/")
                except ValueError:
                    index = 0

                if index >= 4:
                    hostname = tokens[:index]
                else:
                    hostname = tokens

                if hostname[-1] in self._TLDs:
                    return True

        return False


    def _is_maybe_filename(self, string):
            return  "/" in string

    def get_auto_separator(self, context):
        """
        Get word separator to add after inserting a prediction choice.

        Doctests:
        >>> p = PartialURLParser()
        >>> p.get_auto_separator("http")
        '://'
        >>> p.get_auto_separator("www")
        '.'
        >>> p.get_auto_separator("domain.org")
        '/'
        >>> p.get_auto_separator("www.domain.org")
        '/'
        >>> p.get_auto_separator("http://www.domain")
        '.'
        >>> p.get_auto_separator("http://www.domain.org")
        '/'
        >>> p.get_auto_separator("http://www.domain.co") # ambiguous co/ or co.uk/
        '/'
        >>> p.get_auto_separator("http://www.domain.co.uk")
        '/'
        >>> p.get_auto_separator("http://www.domain.co.uk/home")
        '/'
        >>> p.get_auto_separator("http://www.domain.co/home")
        '/'
        >>> p.get_auto_separator("http://www.domain.org/home")
        '/'
        >>> p.get_auto_separator("http://www.domain.org/home/index.html")
        ''
        >>> p.get_auto_separator("mailto")
        ':'

        # local files
        >>> import tempfile
        >>> from os.path import abspath, dirname, join
        >>> def touch(fn):
        ...     with open(fn, mode="w") as f: n = f.write("")
        >>> td = tempfile.TemporaryDirectory(prefix="test onboard _")
        >>> dir = td.name

        >>> touch(join(dir, "onboard-defaults.conf.example"))
        >>> touch(join(dir, "onboard-defaults.conf.example.another"))
        >>>
        >>> import glob
        >>> #glob.glob(dir+"/**")
        >>> p.get_auto_separator("file")
        ':///'
        >>> p.get_auto_separator("file:///home")
        '/'
        >>> p.get_auto_separator("file://"+join(dir, "onboard-defaults"))
        '.'
        >>> p.get_auto_separator("file://"+join(dir, "onboard-defaults.conf"))
        '.'
        >>> p.get_auto_separator("file://"+join(dir, "onboard-defaults.conf.example"))
        ''
        >>> p.get_auto_separator("file://"+join(dir, "onboard-defaults.conf.example.another"))
        ' '

        # Non-existing filename: we don't know, don't guess a separator
        >>> p.get_auto_separator("file:///tmp/onboard1234")
        ''

        # Non-existing filename: if basename has an extension assume we're done
        >>> p.get_auto_separator("file:///tmp/onboard1234.txt")
        ' '

        # Relative filename: we don't know current dir, return empty separator
        >>> p.get_auto_separator("file://tmp")
        ''

        """
        separator = None

        SCHEME, PROTOCOL, DOMAIN, PATH = range(4)
        component = SCHEME
        last_septok = ""
        matches = tuple(self.iter_url(context))
        for index, match in enumerate(matches):
            groups = match.groups()
            token  = groups[0]
            septok = groups[1]

            if septok:
                last_septok = septok
            if index < len(matches)-1:
                next_septok = matches[index+1].groups()[1]
            else:
                next_septok = ""

            if component == SCHEME:
                if token:
                    if token == "file":
                        separator = ":///"
                        component = PATH
                        continue
                    if token in self._schemes:
                        separator = "://"
                        component = DOMAIN
                        continue
                    elif token in self._protocols:
                        separator = ":"
                        component = PROTOCOL
                        continue
                    else:
                        component = DOMAIN

            if component == DOMAIN:
                if token:
                    separator = "."
                    if last_septok == "." and \
                       next_septok != "." and \
                       token in self._TLDs:
                        separator = "/"
                        component = PATH
                        continue

            if component == PATH:
                separator = ""

            if component == PROTOCOL:
                separator = ""

        if component == PATH and not separator:
            file_scheme = "file://"
            if context.startswith(file_scheme):
                filename = context[len(file_scheme):]
                separator = self._get_filename_separator(filename)
            else:
                if not last_septok == ".":
                    separator = "/"

        if separator is None:
             separator = " " # may be entering search terms, keep space as default

        return separator

    def _get_filename_separator(self, filename):
        """
        Get auto separator for a partial filename.
        """
        separator = None

        if os.path.isabs(filename):
            files  = glob.glob(filename + "*")
            files += glob.glob(filename + "/*")  # look inside directories too
            separator = self._get_separator_from_file_list(filename, files)

        if separator is None:
            basename = os.path.basename(filename)
            if "." in basename:
                separator = " "
            else:
                separator = ""

        return separator

    @staticmethod
    def _get_separator_from_file_list(filename, files):
        """
        Extract separator from a list of matching filenames.

        Doctests:
        >>> p = PartialURLParser

        # no matching files: return None, assume new file we can't check
        >>> p._get_separator_from_file_list("/dir/file", [])

        # complete file: we're done, continue with space separator
        >>> p._get_separator_from_file_list("/dir/file.ext", ["/dir/file.ext"])
        ' '

        # multiple files with identical separator: return that separator
        >>> p._get_separator_from_file_list("/dir/file",
        ...                                ["/dir/file.ext1", "/dir/file.ext2"])
        '.'

        # multiple files with different separators: return empty separator
        >>> p._get_separator_from_file_list("/dir/file",
        ...                                ["/dir/file.ext", "/dir/file-ext"])
        ''

        # directory
        >>> p._get_separator_from_file_list("/dir",
        ...                                ["/dir/file.ext1", "/dir/file.ext2"])
        '/'
        >>> p._get_separator_from_file_list("/dir",
        ...                                ["/dir", "/dir/file.ext2"])
        '/'

        # multiple extensions
        >>> files = ["/dir/dir/file.ext1.ext2", "/dir/dir/file.ext1.ext3"]
        >>> p._get_separator_from_file_list("/dir/dir/file", files)
        '.'
        >>> p._get_separator_from_file_list("/dir/dir/file.ext1", files)
        '.'
        >>> p._get_separator_from_file_list("/dir/dir/file.ext1.ext2", files)
        ' '

        # partial path match
        >>> files = ["/dir/dir/file", "/dir/dir/file.ext1",
        ...          "/dir/dir/file.ext2"]
        >>> p._get_separator_from_file_list("/dir/dir/file", files)
        ''
        >>> p._get_separator_from_file_list("/dir/dir/file.ext1", files)
        ' '
        """
        separator = None

        l = len(filename)
        separators = set([f[l:l+1] for f in files \
                         if f.startswith(filename)])

        # directory?
        if len(separators) == 2 and "/" in separators and "" in separators:
            separator = "/"
        # end of filename?
        elif len(separators) == 1 and "" in separators:
            separator = " "
        # unambigous separator?
        elif len(separators) == 1:
            separator = separators.pop()
        # multiple separators
        elif separators:
            separator = ""

        return separator


