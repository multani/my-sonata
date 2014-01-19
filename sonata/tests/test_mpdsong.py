import unittest

from sonata.mpdhelper import MPDSong


class TestMPDSong(unittest.TestCase):
    def test_get_track_number(self):
        self.assertEqual(1, MPDSong({'track': '1'}).track)
        self.assertEqual(1, MPDSong({'track': '1/10'}).track)
        self.assertEqual(1, MPDSong({'track': '1,10'}).track)

    def test_get_disc_number(self):
        self.assertEqual(1, MPDSong({'disc': '1'}).disc)
        self.assertEqual(1, MPDSong({'disc': '1/10'}).disc)
        self.assertEqual(1, MPDSong({'disc': '1,10'}).disc)

    def test_access_attributes(self):
        song = MPDSong({'foo': 'zz', 'id': '5'})

        self.assertEqual(5, song.id)
        self.assertEqual("zz", song.foo)
        self.assertIsInstance(song.foo, str)
        self.assertEqual(song.foo, song.get("foo"))

    def test_get_unknown_attribute(self):
        song = MPDSong({})
        self.assertRaises(KeyError, lambda: song['bla'])
        self.assertEqual(None, song.get('bla'))
        self.assertEqual('foo', song.get('bla', 'foo'))
        self.assertFalse(hasattr(song, 'bla'))

    def test_access_list_attribute(self):
        song = MPDSong({'genre': ['a', 'b'], 'foo': ['c', 'd']})
        self.assertEqual('a', song.genre)
        self.assertEqual('c', song.foo)

    def test_song_pos(self):
        song = MPDSong({'pos': '0'})
        self.assertEqual(0, song.pos)
