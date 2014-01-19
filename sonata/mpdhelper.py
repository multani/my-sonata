
import functools
import logging
import os
import socket

from gi.repository import GObject
import mpd

from sonata.misc import remove_list_duplicates


class MPDClient:
    def __init__(self, client=None):
        if client is None:
            # Yeah, we really want some unicode returned, otherwise we'll have
            # to do it by ourselves.
            client = mpd.MPDClient(use_unicode=True)
        else:
            client.use_unicode = True
        self._client = client
        self.logger = logging.getLogger(__name__)

    def __getattr__(self, attr):
        """
        Wraps all calls from mpd client into a proper function,
        which catches all MPDClient related exceptions and log them.
        """
        cmd = getattr(self._client, attr)
        # save result, so function have to be constructed only once
        wrapped_cmd = functools.partial(self._call, cmd, attr)
        setattr(self, attr, wrapped_cmd)
        return wrapped_cmd

    def _call(self, cmd, cmd_name, *args):
        try:
            retval = cmd(*args)
        except (socket.error, mpd.MPDError) as e:
            if cmd_name in ['lsinfo', 'list']:
                # return sane values, which could be used afterwards
                return []
            elif cmd_name == 'status':
                return {}
            else:
                self.logger.error("%s", e)
                return None

        if cmd_name in ['songinfo', 'currentsong']:
            return MPDSong(retval)
        elif cmd_name in ['plchanges', 'search']:
            return [MPDSong(s) for s in retval]
        elif cmd_name in ['count']:
            return MPDCount(retval)
        else:
            return retval

    @property
    def version(self):
        return tuple(int(part) for part in self._client.mpd_version.split("."))

    def update(self, paths):
        if mpd_is_updating(self.status()):
            return

        # Updating paths seems to be faster than updating files for
        # some reason:
        dirs = []
        for path in paths:
            dirs.append(os.path.dirname(path))
        dirs = remove_list_duplicates(dirs, True)

        self._client.command_list_ok_begin()
        for directory in dirs:
            self._client.update(directory)
        self._client.command_list_end()


class MPDCount:
    """Represent the result of the 'count' MPD command"""

    __slots__ = ['playtime', 'songs']

    def __init__(self, m):
        self.playtime = int(m['playtime'])
        self.songs = int(m['songs'])


# Inherits from GObject for to be stored in Gtk's ListStore
class MPDSong(GObject.GObject):
    """Provide information about a song in a convenient format

    This object has the following properties:

        * it is filled from the result of a MPD command which returns song
          information
        * attributes' values must provide a convenient value, instead of
          providing only strings as the plain MPD protocol does
        * it must provides easy and consistent access to 'basic' song
          attributes, both as properties (clearer code when dealing with songs)
          and as a dictionary (for a more standard interface + accessing
          arbitrary attributes)
        * is must be hashable so it can be used for caching stuff related to
          songs
    """

    def __init__(self, mapping):
        for key, value in mapping.items():
            # Some attributes may be present several times, which is translated
            # into a list of values by python-mpd. We keep only the first one,
            # since Sonata doesn't really support multi-valued attributes at the
            # moment.
            if isinstance(value, list):
                mapping[key] = value[0]

        id_ = mapping.get('id')
        pos = mapping.get('pos', '0')

        # Well-known song fields
        self._mapping = values = {
            'id': int(id_) if id_ is not None else None,
            'album': mapping.get('album'),
            'artist': mapping.get('artist'),
            'date': mapping.get('date'),
            'disc': cleanup_numeric(mapping.get('disc', 0)),
            'file': mapping.get('file', ''), # XXX should be always here?
            'genre': mapping.get('genre'),
            'pos': int(pos) if pos.isdigit() else 0,
            'time': int(mapping.get('time', 0)),
            'title': mapping.get('title'),
            'track': cleanup_numeric(mapping.get('track', '0')),
        }

        for key, value in values.items():
            setattr(self, key, value)

        # Two songs with the same file path are great chances to be the same
        # songs, so we get the hash from this path.
        # If, for some reasons, we don't have any path, we just want objects to
        # have a different hash (this is a very pathological case).
        # We have a special case here: songs will always be different:
        #   * if they have no 'file' attribute
        #   * and if they have at least some other attributes
        # If there's *no* attributes at all, it's a special 'empty' song, which
        # must be dealt accordingly (and equals other 'empty' songs) :(
        if self.file == '' and mapping:
            self._hash = id(self)
        else:
            self._hash = hash(self.file)

        super().__init__()

        # Store extra MPD fields, only for dict-access
        # If this is a valid field, it can be moved to the mapping above.
        for key, value in mapping.items():
            if key not in values:
                self._mapping[key] = value

    def __getitem__(self, key):
        return self._mapping[key]

    def __contains__(self, key):
        return key in self._mapping

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return hash(self) != hash(other)

    def __hash__(self):
        return self._hash

    def get(self, key, default=None):
        try:
            value = self[key]
            if value is None:
                value = default
        except KeyError:
            value = default
        return value

    def __iter__(self):
        for key, value in self._mapping.items():
            if value is None:
                value = ''
            if not isinstance(value, str):
                value = str(value)

            yield(key, value)


def cleanup_numeric(value):
    # track and disc can be oddly formatted (eg, '4/10')
    value = str(value).replace(',', ' ').replace('/', ' ').split()[0]
    return int(value) if value.isdigit() else 0

# XXX to be move when we can handle status change in the main interface
def mpd_is_updating(status):
    return status and status.get('updating_db', 0)
