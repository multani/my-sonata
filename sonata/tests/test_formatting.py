import doctest
import unittest

from sonata import formatting


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

        self.assertEqual("bar", f.format(self.item, None, None))
        self.assertEqual("default", f.format({}, None, None))

    def test_number_format(self):
        f = formatting.NumFormatCode(None, None, None, "num", 42, 6)

        self.assertEqual("000005", f.format(self.item, None, None))
        self.assertEqual("000042", f.format({}, None, None))

    def test_path_format(self):
        f = formatting.PathFormatCode(None, None, None, "path", "dirname")

        self.assertEqual("/plop/plip", f.format(self.item, None, None))
        self.assertEqual("", f.format({}, None, None))

    def test_title_format_local_file(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "/tmp/foo.mp3", "foo": "bar"}
        self.assertEqual("bar", f.format(item, None, None))

        item = {"file": "/tmp/foo.mp3"}
        self.assertEqual("foo.mp3", f.format(item, None, None))

        item = {"file": "foo.mp3"}
        self.assertEqual("foo.mp3", f.format(item, None, None))

    def test_title_format_remote_file(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "http://example.com/foo.mp3"}
        self.assertEqual("http://example.com/foo.mp3", f.format(item, None, None))

        item = {"file": "ftp://example.com/foo.mp3"}
        self.assertEqual("ftp://example.com/foo.mp3", f.format(item, None, None))

    def test_title_format_escape_html(self):
        f = formatting.TitleFormatCode(None, None, None, "foo", "default")

        item = {"file": "http://example.com/foo.mp3<div>plop</div>",
                "foo": "bar<div>plop</div>"}
        self.assertEqual("bar<div>plop</div>", f.format(item, None, None))

        item = {"file": "http://example.com/foo.mp3<div>plop</div>"}
        self.assertEqual("http://example.com/foo.mp3&lt;div&gt;plop&lt;/div&gt;",
                         f.format(item, None, None))

    def test_length_format(self):
        f = formatting.LenFormatCode(None, None, None, "num", "default")

        self.assertEqual("00:05", f.format(self.item, None, None))
        self.assertEqual("16:18", f.format({'num': 978}, None, None))
        self.assertEqual("default", f.format({}, None, None))

    def test_elapsed_format_not_wintitle(self):
        f = formatting.ElapsedFormatCode(None, None, None, None, "default")

        self.assertEqual("%E", f.format(self.item, False, None))

    def test_elapsed_format(self):
        f = formatting.ElapsedFormatCode(None, None, None, None, "default")

        self.assertEqual("03:02", f.format(self.item, True, "182:286"))

        # This happens if MPD doesn't return the "time" line in response to the
        # "status" command
        self.assertEqual("default", f.format(self.item, True, None))


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
    func = staticmethod(formatting.parse_colnames)

    def test_empty(self):
        self.assertEqual([""], self.func(""))

    def test_no_column(self):
        self.assertEqual(["foo"], self.func("foo"))

    def test_one_column(self):
        self.assertEqual(["foo", "bar"], self.func("foo|bar"))

    def test_several_columns(self):
        self.assertEqual(["foo", "bar", " baz"], self.func("foo|bar| baz"))

    def test_one_code(self):
        self.assertEqual(["Artist"], self.func("%A"))

    def test_multiple_codes(self):
        self.assertEqual(["Artist Album %3", "Track"],
                         self.func("%A %B %3|%T"))

    def test_with_substrings(self):
        self.assertEqual(["Artist -Track", "Len"], self.func("%A {-%T}|{%L}"))

    def test_with_dash(self):
        self.assertEqual(["#"], self.func("%N"))
        self.assertEqual(["#"], self.func("#%N"))


class TestFormatSubstrings(unittest.TestCase):
    func = staticmethod(formatting._format_substrings)

    def test_empty(self):
        self.assertEqual("", self.func("", {}, None, None))

    def test_simple(self):
        self.assertEqual('Art: Foo',
                         self.func("Art: %A", {'artist': 'Foo'}, None, None))

    def test_value_not_available(self):
        self.assertEqual('Art: Unknown',
                         self.func("Art: %A", {}, None, None))

    def test_with_brackets_filled(self):
        self.assertEqual('Art: Foo',
                         self.func("{Art: %A}", {'artist': 'Foo'}, None, None))

    def test_with_brackets_unfilled(self):
        self.assertEqual('',
                         self.func("{Alb: %B}", {'artist': 'Foo'}, None, None))

    def test_with_unmatched_brackets_filled(self):
        self.assertEqual('Art: Foo}',
                         self.func("Art: %A}", {'artist': 'Foo'}, None, None))

        self.assertEqual('{Art: Foo',
                         self.func("{Art: %A", {'artist': 'Foo'}, None, None))


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

    def test_with_wintitle(self):
        self.assertEqual('Time: ?',
                         self.func("Time: %E", {}, False, True))

        self.assertEqual('Time: 01:06',
                         self.func("Time: %E", {}, False, True, '66'))

    def test_with_no_wintitle(self):
        self.assertEqual('Time: %E',
                         self.func("Time: %E", {}, False, False, '66'))


def additional_tests():
    return unittest.TestSuite(
        doctest.DocFileSuite('../formatting.py', optionflags=DOCTEST_FLAGS),
    )
