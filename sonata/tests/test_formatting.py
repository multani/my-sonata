import doctest
import unittest

from sonata import formatting
from sonata.mpdhelper import MPDSong


DOCTEST_FLAGS = (
    doctest.ELLIPSIS |
    doctest.NORMALIZE_WHITESPACE |
    doctest.REPORT_NDIFF
)


class TestFormatCode(unittest.TestCase):
    def setUp(self):
        self.item = {
            "foo": "bar",
            "num": 5,
            "path": "/plop/plip/plap",
        }

    def test_default_format_code(self):
        f = formatting.FormatCode(None, None, None, "foo", "default")

        self.assertEqual("bar", f.format(self.item))
        self.assertEqual("default", f.format({}))

    def test_number_format(self):
        f = formatting.NumFormatCode(None, None, None, "num", 42, 6)

        self.assertEqual("000005", f.format(self.item))
        self.assertEqual("000042", f.format({}))

    def test_path_format(self):
        f = formatting.PathFormatCode(None, None, None, "path", "dirname")

        self.assertEqual("/plop/plip", f.format(self.item))
        self.assertEqual("", f.format({}))

    def test_title_format_local_file(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "/tmp/foo.mp3", "foo": "bar"}
        self.assertEqual("bar", f.format(item))

        item = {"file": "/tmp/foo.mp3"}
        self.assertEqual("foo.mp3", f.format(item))

        item = {"file": "foo.mp3"}
        self.assertEqual("foo.mp3", f.format(item))

    def test_title_format_remote_file(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "http://example.com/foo.mp3"}
        self.assertEqual("http://example.com/foo.mp3", f.format(item))

        item = {"file": "ftp://example.com/foo.mp3"}
        self.assertEqual("ftp://example.com/foo.mp3", f.format(item))

    def test_title_format_escape_html(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "http://example.com/foo.mp3<div>plop</div>",
                "foo": "bar<div>plop</div>"}
        self.assertEqual("bar<div>plop</div>", f.format(item))

        item = {"file": "http://example.com/foo.mp3<div>plop</div>"}
        self.assertEqual("http://example.com/foo.mp3&lt;div&gt;plop&lt;/div&gt;",
                         f.format(item))

    def test_length_format(self):
        f = formatting.LenFormatCode(None, None, None, "num", "default")

        self.assertEqual("00:05", f.format(self.item))
        self.assertEqual("16:18", f.format({'num': 978}))
        self.assertEqual("default", f.format({}))

    def test_elapsed_format(self):
        f = formatting.ElapsedFormatCode(None, None, None, None, "default")

        self.assertEqual("%E", f.format({}))
        self.assertEqual("03:02", f.format({'status:time': '182:286'}))

        # This happens if MPD doesn't return the "time" line in response to the
        # "status" command
        self.assertEqual("default", f.format({'status:time': None}))


class TestParsingSubString(unittest.TestCase):
    func = staticmethod(formatting._return_substrings)

    def test_empty(self):
        self.assertEqual([], self.func(""))

    def test_no_substring(self):
        self.assertEqual(["foo bar", ""], self.func("foo bar"))

    def test_one_substring(self):
        self.assertEqual(["", "{foo}"], self.func("{foo}"))

    def test_two_substrings(self):
        self.assertEqual(["", "{foo}", "", "{bar}"], self.func("{foo}{bar}"))

    def test_unfinished_substring(self):
        self.assertEqual(["", "{foo"], self.func("{foo"))


class TestParseColumnName(unittest.TestCase):
    def test_empty(self):
        f = formatting.ColumnFormatting("")
        self.assertEqual([""], f.columns_names)

    def test_no_column(self):
        f = formatting.ColumnFormatting("foo")
        self.assertEqual(["foo"], f.columns_names)

    def test_one_column(self):
        f = formatting.ColumnFormatting("foo|bar")
        self.assertEqual(["foo", "bar"], f.columns_names)

    def test_several_columns(self):
        f = formatting.ColumnFormatting("foo|bar| baz")
        self.assertEqual(["foo", "bar", " baz"], f.columns_names)

    def test_one_code(self):
        f = formatting.ColumnFormatting("%A")
        self.assertEqual(["Artist"], f.columns_names)

    def test_multiple_codes(self):
        f = formatting.ColumnFormatting("%A %B %3|%T")
        self.assertEqual(["Artist Album %3", "Track"],
                         f.columns_names)

    def test_with_substrings(self):
        f = formatting.ColumnFormatting("%A {-%T}|{%L}")
        self.assertEqual(["Artist -Track", "Len"], f.columns_names)

    def test_with_dash(self):
        f = formatting.ColumnFormatting("%N")
        self.assertEqual(["#"], f.columns_names)

        f = formatting.ColumnFormatting("#%N")
        self.assertEqual(["#"], f.columns_names)


class TestFormatSubstrings(unittest.TestCase):
    func = staticmethod(formatting._format_substrings)

    def test_empty(self):
        self.assertEqual("", self.func("", {}))

    def test_simple(self):
        self.assertEqual('Art: Foo',
                         self.func("Art: %A", {'artist': 'Foo'}))

    def test_value_not_available(self):
        self.assertEqual('Art: Unknown',
                         self.func("Art: %A", {}))

    def test_with_brackets_filled(self):
        self.assertEqual('Art: Foo',
                         self.func("{Art: %A}", {'artist': 'Foo'}))

    def test_with_brackets_unfilled(self):
        self.assertEqual('',
                         self.func("{Alb: %B}", {'artist': 'Foo'}))

    def test_with_unmatched_brackets_filled(self):
        self.assertEqual('Art: Foo}',
                         self.func("Art: %A}", {'artist': 'Foo'}))

        self.assertEqual('{Art: Foo',
                         self.func("{Art: %A", {'artist': 'Foo'}))


class TestParseAndFormat(unittest.TestCase):
    func = staticmethod(formatting.parse)

    def test_empty(self):
        self.assertEqual("", self.func("", {}, False))

    def test_simple(self):
        self.assertEqual('Art: Foo',
                         self.func("Art: %A", {'artist': 'Foo'}, False))

    def test_value_not_available(self):
        self.assertEqual('Art: Unknown',
                         self.func("Art: %A", {}, False))

    def test_with_brackets_filled(self):
        self.assertEqual('Art: Foo',
                         self.func("{Art: %A}", {'artist': 'Foo'}, False))

    def test_with_brackets_unfilled(self):
        self.assertEqual('',
                         self.func("{Alb: %B}", {'artist': 'Foo'}, False))

    def test_escape_html(self):
        self.assertEqual('Art: &lt;Foo&gt;',
                         self.func("Art: %A", {'artist': '<Foo>'}, True))

    def test_several_formatters(self):
        self.assertEqual('Art: Foo - Alb: Bar',
                         self.func("Art: %A - Alb: %B",
                                   {'artist': 'Foo', 'album': 'Bar'}, False))


class TestFormatMPDSong(unittest.TestCase):
    """Format a real MPD Song object"""

    func = staticmethod(formatting.parse)

    def test_format_simple_song(self):
        song = MPDSong({'artist': 'artist',
                        'album': 'album',
                        'track': '42'})

        self.assertEqual('Art: artist - Alb: album - Track: 42',
                         self.func("Art: %A - Alb: %B - Track: %N",
                                   song, False))


class TestFormatColumns(unittest.TestCase):
    def test_columns_names(self):
        f = formatting.ColumnFormatting('%A|%B|%N')
        self.assertEqual(['Artist', 'Album', '#'], f.columns_names)

        f = formatting.ColumnFormatting('%Y')
        self.assertEqual(['Year'], f.columns_names)

    def test_len_formatter(self):
        f = formatting.ColumnFormatting('%A|%B|%N')
        self.assertEqual(3, len(f))

        f = formatting.ColumnFormatting('%D')
        self.assertEqual(1, len(f))

    def test_empty_columns(self):
        # Pathological case
        f = formatting.ColumnFormatting('')
        self.assertEqual(1, len(f))

        f = formatting.ColumnFormatting('')
        self.assertEqual([''], f.columns_names)


class TestCachingFormatter(unittest.TestCase):
    def make_song(self, extras={}):
        values = {'artist': 'artist',
                  'album': 'album',
                  'file': 'foo/bar.ext',
                  'track': '42'}
        values.update(extras)
        return MPDSong(values)

    def test_simple(self):
        song = self.make_song()

        f = formatting.CachingFormatter('%A')
        self.assertEqual('artist', f.format(song))

        f = formatting.CachingFormatter('%A %B')
        self.assertEqual('artist album', f.format(song))

    def test_escape_html(self):
        song = self.make_song({'artist': '<b>&h!'})

        f = formatting.CachingFormatter('%A')
        self.assertEqual('<b>&h!', f.format(song))

        f = formatting.CachingFormatter('%A', True)
        self.assertEqual('&lt;b&gt;&amp;h!', f.format(song))

    def test_cache(self):
        song = self.make_song()

        class TestCachingFormatter(formatting.CachingFormatter):
            # Catch formatting calls, to test the caching process
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.called = 0

                def format(*a, **k):
                    self.called += 1
                    return "foo"

                self._format_func = format

        f = TestCachingFormatter('%A')
        self.assertEqual(0, len(f._cache))
        self.assertEqual(0, f.called)

        self.assertEqual('foo', f.format(song))
        self.assertEqual(1, len(f._cache))
        self.assertEqual(1, f.called)

        self.assertEqual('foo', f.format(song))
        # Already formatted and should be in the cache, no new call made
        self.assertEqual(1, f.called)

        del song
        self.assertEqual(0, len(f._cache))


def additional_tests():
    return unittest.TestSuite(
        doctest.DocFileSuite('../formatting.py', optionflags=DOCTEST_FLAGS),
    )
