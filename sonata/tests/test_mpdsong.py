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
        song = MPDSong({})

        # Those attributes are *always* here
        attrs = ['id', 'album', 'artist', 'date', 'disc', 'file', 'genre',
                 'pos', 'time', 'title', 'track']
        for attr in attrs:
            getattr(song, attr)

    def test_access_extra_attributes(self):
        song = MPDSong({'foo': 'zz'})

        with self.assertRaises(AttributeError):
            __ = song.foo

        self.assertIn('foo', song)
        self.assertEqual('zz', song['foo'])
        self.assertEqual('zz', song.get('foo'))

    def test_access_unset_default_attribute(self):
        song = MPDSong({})

        self.assertEqual(None, song.get('artist'))
        self.assertEqual('foo', song.get('artist', 'foo'))

    def test_get_unknown_attribute(self):
        song = MPDSong({})
        self.assertRaises(KeyError, lambda: song['bla'])
        self.assertEqual(None, song.get('bla'))
        self.assertEqual('foo', song.get('bla', 'foo'))

    def test_access_list_attribute(self):
        song = MPDSong({'genre': ['a', 'b'], 'foo': ['c', 'd']})

        self.assertEqual('a', song.genre)
        self.assertEqual('c', song['foo'])

    def test_song_pos(self):
        song = MPDSong({'pos': '0'})
        self.assertEqual(0, song.pos)

    def test_contains(self):
        song = MPDSong({'pos': '0'})
        self.assertIn('pos', song)
        self.assertNotIn('stuff', song)

    def test_copy_as_dict(self):
        song = MPDSong({'id': '5'})
        d = dict(song)

        self.assertEqual('5', d['id'])
        self.assertEqual('', d['album'])

    def test_equality(self):
        song1 = MPDSong({'file': 'foo/bar.ext'})
        song2 = MPDSong({'file': 'foo/bar.ext'})
        song3 = MPDSong({'file': 'toto/tata/titi.song'})

        self.assertTrue (song1 == song2)
        self.assertFalse(song1 != song2)

        self.assertTrue (song1 != song3)
        self.assertFalse(song1 == song3)

        self.assertTrue (song2 != song3)
        self.assertFalse(song2 == song3)

    def test_hash(self):
        song1 = MPDSong({'file': 'foo/bar.ext'})
        song2 = MPDSong({'file': 'foo/bar.ext'})
        song3 = MPDSong({'file': 'toto/tata/titi.song'})

        self.assertEqual(hash(song1), hash(song2))
        self.assertNotEqual(hash(song1), hash(song3))
        self.assertNotEqual(hash(song2), hash(song3))

    def test_hash_with_not_enough_info(self):
        # Different, even if they have the same attributes, since we 'file' is
        # used to discriminate songs.
        song1 = MPDSong({'id': '5'})
        song2 = MPDSong({'id': '5'})

        self.assertNotEqual(hash(song1), hash(song2))
        self.assertNotEqual(song1, song2)

    def test_hash_with_empty_values(self):
        song1 = MPDSong({})
        song2 = MPDSong({})

        self.assertEqual(hash(song1), hash(song2))
        self.assertEqual(song1, song2)
