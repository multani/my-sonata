import os
import re
import gettext
import locale
import threading
import operator

from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib, Pango

from sonata import ui, misc, consts, formatting, breadcrumbs
from sonata.song import SongRecord

VARIOUS_ARTISTS = _("Various Artists")
NOTAG = _("Untagged")

def list_mark_various_artists_albums(albums):
    for i in range(len(albums)):
        if i + consts.NUM_ARTISTS_FOR_VA - 1 > len(albums)-1:
            break
        VA = False
        for j in range(1, consts.NUM_ARTISTS_FOR_VA):
            if (albums[i].album.lower() != albums[i + j].album.lower() or
                    albums[i].year  != albums[i + j].year or
                    albums[i].path  != albums[i + j].path):
                break
            if albums[i].artist == albums[i + j].artist:
                albums.pop(i + j)
                break
            if j == consts.NUM_ARTISTS_FOR_VA - 1:
                VA = True
        if VA:
            albums[i].artist = VARIOUS_ARTISTS
            j = 1
            while i + j <= len(albums) - 1:
                if (albums[i].album.lower() == albums[i + j].album.lower() and
                        albums[i].year == albums[i + j].year):
                    albums.pop(i + j)
                else:
                    break
    return albums


class LibrarySearch(object):
    SEARCH_TERMS = ('artist', 'title', 'album', 'genre', 'file', 'any')
    def __init__(self, mpd):
        self.mpd = mpd
        self.cache_genres = None
        self.cache_artists = None
        self.cache_albums = None
        self.cache_years = None

        # Used for the actual filtering search
        # These two are the only ones modified by the Main Thread
        self.search_num = None
        self.search_input = None

        self.search_previous_count = None
        self.search_base = None
        self.search_by = None
        self.search_cache = None
        self.subsearch = False

    def invalidate_cache(self):
        self.cache_genres = None
        self.cache_artists = None
        self.cache_albums = None
        self.cache_years = None

    def get_count(self, song_record):
        # Because mpd's 'count' is case sensitive, we have to
        # determine all equivalent items (case insensitive) and
        # call 'count' for each of them. Using 'list' + 'count'
        # involves much less data to be transferred back and
        # forth than to use 'search' and count manually.
        searches = self.get_lists(song_record)
        playtime = 0
        num_songs = 0
        for s in searches:
            count = self.mpd.count(*s)
            playtime += count.playtime
            num_songs += count.songs

        return (playtime, num_songs)

    def get_list(self, search, typename, cached_list, searchlist):
        s = []
        skip_type = (typename == 'artist' and search == VARIOUS_ARTISTS)
        if search is not None and not skip_type:
            if search == NOTAG:
                itemlist = [search, '']
            else:
                itemlist = []
                if cached_list is None:
                    cached_list = self.get_list_items(typename, SongRecord(),
                                                      ignore_case=False)
                    # This allows us to match untagged items
                    cached_list.append('')
                for item in cached_list:
                    if str(item).lower() == str(search).lower():
                        itemlist.append(item)
            if len(itemlist) == 0:
                # There should be no results!
                return None, cached_list
            for item in itemlist:
                if len(searchlist) > 0:
                    for item2 in searchlist:
                        s.append(item2 + (typename, item))
                else:
                    s.append((typename, item))
        else:
            s = searchlist
        return s, cached_list

    def get_lists(self, song_record):
        s = []
        s, self.cache_genres = self.get_list(song_record.genre, 'genre',
                                             self.cache_genres, s)
        if s is None:
            return []
        s, self.cache_artists = self.get_list(song_record.artist, 'artist',
                                              self.cache_artists, s)
        if s is None:
            return []
        s, self.cache_albums = self.get_list(song_record.album, 'album',
                                             self.cache_albums, s)
        if s is None:
            return []
        s, self.cache_years = self.get_list(song_record.year, 'date',
                                            self.cache_years, s)
        if s is None:
            return []
        return s

    def get_search(self, search, typename, searchlist):
        s = []
        skip_type = (typename == 'artist' and search == VARIOUS_ARTISTS)
        if search is not None and not skip_type:
            if search == NOTAG:
                itemlist = [search, '']
            else:
                itemlist = [search]
            for item in itemlist:
                if len(searchlist) > 0:
                    for item2 in searchlist:
                        s.append(item2 + (typename, item))
                else:
                    s.append((typename, item))
        else:
            s = searchlist
        return s

    def get_searches(self, song_record):
        s = []
        s = self.get_search(song_record.genre, 'genre', s)
        s = self.get_search(song_record.album, 'album', s)
        s = self.get_search(song_record.artist, 'artist', s)
        s = self.get_search(song_record.year, 'date', s)
        return s

    def get_search_items(self, song_record):
        # Returns all mpd items, using mpd's 'search', along with
        # playtime and num_songs.

        playtime = 0
        num_songs = 0
        results = []

        searches = self.get_searches(song_record)
        for s in searches:
            args_tuple = tuple(map(str, s))

            if len(args_tuple) == 0:
                return None, 0, 0

            for item in self.mpd.search(*args_tuple):
                match = True
                # Ensure that if, e.g., "foo" is searched,
                # "foobar" isn't returned too
                for arg, arg_val in zip(args_tuple[::2], args_tuple[1::2]):
                    if (arg in item and
                            str(item.get(arg, '')).upper() != arg_val.upper()):
                        match = False
                        break
                if match:
                    results.append(item)
                    num_songs += 1
                    playtime += item.time
        return (results, int(playtime), num_songs)

    def get_list_items(self, itemtype, song_record, ignore_case=True):
        # Returns all items of tag 'itemtype', in alphabetical order,
        # using mpd's 'list'. If searchtype is passed, use
        # a case insensitive search, via additional 'list'
        # queries, since using a single 'list' call will be
        # case sensitive.
        results = []
        searches = self.get_lists(song_record)
        if len(searches) > 0:
            for s in searches:
                # If we have untagged tags (''), use search instead
                # of list because list will not return anything.
                if '' in s:
                    songs, _playtime, _num_songs =  self.get_search_items(
                        song_record)
                    items = [song.get(itemtype, '') for song in songs]
                else:
                    items = self.mpd.list(itemtype, *s)
                results.extend([item for item in items if len(item) > 0])
        else:
            no_search = [val is None for val in (song_record.genre,
                                                 song_record.artist,
                                                 song_record.album,
                                                 song_record.year)]
            if all(no_search):
                items = self.mpd.list(itemtype)
                results = [item for item in items if len(item) > 0]
        if ignore_case:
            results = misc.remove_list_duplicates(results, case=False)
        results.sort(key=locale.strxfrm)
        return results

    def cleanup_search(self):
        # Main Thread
        self.search_num = None
        self.search_input = None

        self.search_previous_count = None
        self.search_base = None
        self.search_by = None
        self.search_cache = None
        self.subsearch = False

    def request_search(self, search_thread_cb):
        # Search Thread
        search_by = self.SEARCH_TERMS[self.search_num]
        search_base = self.search_input[:2]
        if (self.search_base is None or self.search_base != search_base or
                self.search_by is None or self.search_by != search_by):
            self.search_base = search_base
            GLib.idle_add(self.perform_search, search_thread_cb)
            self.subsearch = False
        else:
            self.subsearch = True
            search_thread_cb()

    def perform_search(self, search_thread_cb):
        # Main Thread
        # Do library search based on first two letters
        # This is cached so that similar subsearches will complete faster
        search_by = self.SEARCH_TERMS[self.search_num]
        self.search_cache = self.mpd.search(search_by, self.search_base)
        search_thread_cb()

    def filter_search_data(self):
        # Search Thread
        # Now, use filtering similar to playlist filtering:
        # this make take some seconds... and we'll escape the search text
        # because we'll be searching for a match in items that are also escaped
        #
        # Note that the searching is not order specific. That is, "foo bar"
        # will match on "fools bar" and "barstool foo".

        search_by = self.SEARCH_TERMS[self.search_num]
        searches = self.search_input.split(" ")
        regexps = []
        for search in searches:
            search = misc.escape_html(search)
            search = re.escape(search)
            search = '.*' + search.lower()
            regexps.append(re.compile(search))
        matches = []
        if search_by == 'any':
            str_data = lambda row, search_by: str(" ".join(row.values()))
        else:
            str_data = lambda row, search_by: row.get(search_by, '')
        for row in self.search_cache:
            is_match = True
            for regexp in regexps:
                if not regexp.match(str_data(row, search_by).lower()):
                    is_match = False
                    break
            if is_match:
                matches.append(row)
        # The changed search didn't change the results
        # FIXME This fails for two different result sets with same length.
        if self.subsearch and len(matches) == self.search_previous_count:
            return None
        self.search_previous_count = len(matches)
        return matches


# This thread performs the actual filtering, but because of how we connect to
# MPD, it still gets the data from MPD on the main thread.
# Without doing this, the results are not stable, though it does make our
# code more complicated to do it this way.
class LibrarySearchThread(threading.Thread, GObject.GObject):
    # search_ready means the results are there to be loaded in the UI
    # search_stopped means the thread has nothing to do and should be ended
    # until new data is available
    __gsignals__ = {
        'search_ready': (GObject.SIGNAL_RUN_FIRST, None,
                         (GObject.TYPE_PYOBJECT,)),
        'search_stopped': (GObject.SIGNAL_RUN_FIRST, None,
                           (GObject.TYPE_PYOBJECT,)),
    }
    def __init__(self, search, search_condition):
        threading.Thread.__init__(self)
        GObject.GObject.__init__(self)
        self.name = "Library Search Thread"
        self.daemon = True
        self.search = search
        self.condition = search_condition
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self.input = None
        self.search_num = None

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def ready(self):
        self._ready_event.set()

    def done(self):
        self._ready_event.clear()

    def awaiting_data(self):
        return not self._ready_event.is_set()

    def run(self):
        while True:
            input_changed = False
            self.condition.acquire()
            while (not self.stopped() and self.awaiting_data() and
                   self.input == self.search.search_input and
                   self.search_num == self.search.search_num):
                self.condition.wait()
            input_changed = self.input != self.search.search_input
            num_changed = self.search_num != self.search.search_num
            if input_changed or num_changed:
                self.input = self.search.search_input
                self.search_num = self.search.search_num
            elif not self.awaiting_data():
                self.filter_search_data()
            self.done()
            self.condition.notify_all()
            self.condition.release()

            if self.stopped():
                return

            input_len = len(self.input)
            # Only search when we have at least two characters,
            # call it quits when we have none
            if (input_changed or num_changed) and input_len > 1:
                self.request_search()
            elif input_len == 0:
                # The second argument is to tell search_toggle not to refocus
                # on the library
                GLib.idle_add(self.emit, 'search_stopped', False)

    def ready_cb(self):
        # Main Thread, Search Threads (see LibrarySearch.request_search)
        self.ready()
        with self.condition:
            self.condition.notify_all()

    def request_search(self):
        # Search Thread
        # Simple wrapper for holding the condition and not signaling if no
        # change in results
        with self.condition:
            self.search.request_search(self.ready_cb)
            self.condition.notify_all()

    def filter_search_data(self):
        # Search Thread
        search_data = self.search.filter_search_data()
        if search_data is not None:
            GLib.idle_add(self.emit, 'search_ready', search_data)


class LibraryView(object):
    TYPE_ALBUM = 'album'
    TYPE_ARTIST = 'artist'
    TYPE_FOLDER = 'folder'
    TYPE_GENRE = 'genre'
    TYPE_SONG = 'song'
    view_type = None
    name = None
    label = None
    icon = None
    def __init__(self, library):
        self.cache = None
        self.data_rows = {}
        self.library = library
        self.artwork = self.library.artwork
        self.config = self.library.config
        self.search = self.library.search

        self.artist_icon = 'sonata-artist'
        self.artist_pixbuf = self.library.tree.render_icon_pixbuf(
            self.artist_icon, Gtk.IconSize.LARGE_TOOLBAR)
        self.album_icon = 'sonata-album'
        self.album_pixbuf = self.library.tree.render_icon_pixbuf(
            self.album_icon, Gtk.IconSize.LARGE_TOOLBAR)
        self.genre_icon = Gtk.STOCK_ORIENTATION_PORTRAIT
        self.genre_pixbuf = self.library.tree.render_icon_pixbuf(
            self.genre_icon, Gtk.IconSize.LARGE_TOOLBAR)

        self.folder_icon = Gtk.STOCK_HARDDISK
        self.folder_pixbuf = self.library.tree.render_icon_pixbuf(
            Gtk.STOCK_OPEN, Gtk.IconSize.MENU)
        self.song_icon = 'sonata'
        self.song_pixbuf = self.library.tree.render_icon_pixbuf(
            self.song_icon, Gtk.IconSize.MENU)

    def invalidate_row_cache(self):
        self.data_rows = {}

    def invalidate_cache(self):
        self.cache = None
        self.invalidate_row_cache()

    def add_display_info(self, num_songs, playtime):
        seconds = int(playtime)
        hours   = seconds // 3600
        seconds -= 3600 * hours
        minutes = seconds // 60
        seconds -= 60 * minutes
        songs_text = ngettext('{count} song', '{count} songs',
                              num_songs).format(count=num_songs)
        seconds_text = ngettext('{count} second', '{count} seconds',
                                seconds).format(count=seconds)
        minutes_text = ngettext('{count} minute', '{count} minutes',
                                minutes).format(count=minutes)
        hours_text = ngettext('{count} hour', '{count} hours',
                              hours).format(count=hours)
        time_parts = [songs_text]
        if hours > 0:
            time_parts.extend([hours_text, minutes_text])
        elif minutes > 0:
            time_parts.extend([minutes_text, seconds_text])
        else:
            time_parts.extend([seconds_text])
        display_markup = "\n<small><span weight='light'>{}</span></small>"
        display_text = ', '.join(time_parts)
        return display_markup.format(display_text)

    def get_action_name(self):
        return self.name + 'view'

    def get_action(self, action):
        return (self.get_action_name(), self.icon, self.label, None, None,
                action)

    def get_data_level(self, song_record):
        # Returns the number of items stored in data
        return sum([1 for item in song_record if item is not None])

    def get_parent(self, wd):
        return self._get_parent(wd)

    def _get_parent(self, wd):
        path = '/'
        if wd.path:
            path = os.path.dirname(wd.path)
        return SongRecord(path=path)

    def _get_crumb_data(self, keys, nkeys, parts):
        crumbs = []
        # append a crumb for each part
        for i, key, part in zip(range(nkeys), keys, parts):
            if part is None:
                continue
            partdata = dict(list(zip(keys, parts))[:i + 1])
            target = SongRecord(**partdata)
            pb, icon = None, None
            if key == 'album':
                # Album artwork, with self.album_icon as a backup:
                cache_data = SongRecord(artist=self.config.wd.artist,
                                        album=self.config.wd.album,
                                        path=self.config.wd.path)
                pb = self.artwork.get_album_row_pixbuf(cache_data, priority=9)
                if not pb:
                    icon = self.album_icon
            elif key == 'artist':
                icon = self.artist_icon
            else:
                icon = self.genre_icon
            crumbs.append((part, icon, pb, target))
        return crumbs

    def get_crumb_data(self):
        keys = 'genre', 'artist', 'album'
        nkeys = 3
        parts = (self.config.wd.genre, self.config.wd.artist,
                 self.config.wd.album)
        return self._get_crumb_data(keys, nkeys, parts)

    def _get_toplevel_data(self):
        pass

    def _get_artists_data(self, song_record):
        bd = []
        if song_record.genre is None:
            return bd
        artists = self.search.get_list_items('artist', song_record)
        if len(artists) == 0:
            return bd
        if not NOTAG in artists:
            artists.append(NOTAG)
        for artist in artists:
            artist_data = SongRecord(genre=song_record.genre, artist=artist)
            playtime, num_songs = self.search.get_count(artist_data)
            if num_songs > 0:
                display = misc.escape_html(artist)
                display += self.add_display_info(num_songs, playtime)
                row_data = [self.artist_pixbuf, artist_data, display,
                            self.TYPE_ARTIST]
                bd += [(misc.lower_no_the(artist), row_data)]
        return bd

    def _get_albums_data(self, song_record):
        bd = []
        if song_record.artist is None:
            return bd
        albums = self.search.get_list_items('album', song_record)
        # Albums first:
        for album in albums:
            album_data = SongRecord(genre=song_record.genre,
                                    artist=song_record.artist,
                                    album=album)
            years = self.search.get_list_items('date', album_data)
            if not NOTAG in years:
                years.append(NOTAG)
            for year in years:
                album_data = SongRecord(genre=song_record.genre,
                                        artist=song_record.artist,
                                        album=album, year=year)
                playtime, num_songs = self.search.get_count(album_data)
                if num_songs > 0:
                    files = self.search.get_list_items('file', album_data)
                    path = os.path.dirname(files[0])
                    album_data.path = path
                    display = misc.escape_html(album)
                    if year and len(year) > 0 and year != NOTAG:
                        year_str = " <span weight='light'>({year})</span>"
                        display += year_str.format(year=misc.escape_html(year))
                    display += self.add_display_info(num_songs, playtime)
                    ordered_year = year
                    if ordered_year == NOTAG:
                        ordered_year = '9999'
                    row_data = [self.album_pixbuf, album_data, display,
                                self.TYPE_ALBUM]
                    bd += [(ordered_year + misc.lower_no_the(album), row_data)]
        # Sort early to add pb in display order
        bd.sort(key=lambda key: locale.strxfrm(key[0]))
        for album_row in bd:
            data = album_row[1][1]
            cache_key = SongRecord(artist=data.artist, album=data.album,
                                   path=data.path)
            pb = self.artwork.get_album_row_pixbuf(cache_key)
            if pb:
                album_row[1][0] = pb
        # Now, songs not in albums:
        non_albums = SongRecord(genre=song_record.genre,
                                artist=song_record.artist,
                                album=NOTAG)
        bd += self._get_data_songs(non_albums)
        return bd

    def _get_data(self, song_record):
        # Create treeview model info
        bd = []
        genre, artist, album = (song_record.genre, song_record.artist,
                                song_record.album)
        if genre is not None and artist is None and album is None:
            # Artists within a genre
            bd = self._get_artists_data(song_record)
        elif artist is not None and album is None:
            # Albums/songs within an artist and possibly genre
            bd = self._get_albums_data(song_record)
        else:
            # Songs within an album, artist, year, and possibly genre
            bd = self._get_data_songs(song_record)
        bd.sort(key=lambda key: locale.strxfrm(key[0]))
        return bd

    def song_row(self, song):
        return [self.song_pixbuf, SongRecord(path=song['file']),
                formatting.parse(self.config.libraryformat, song, True),
                self.TYPE_SONG]

    def _get_data_songs(self, song_record):
        bd = []
        songs, _playtime, _num_songs = self.search.get_search_items(song_record)

        for song in songs:
            track = str(song.get('track', 99)).zfill(2)
            disc = str(song.get('disc', 99)).zfill(2)
            song_data = self.song_row(song)
            sort_data = 'f{disc}{track}'.format(disc=disc, track=track)
            try:
                song_title = misc.lower_no_the(song.title)
            except:
                song_title = song.file.lower()
            sort_data += song_title
            bd += [(sort_data, song_data)]
        return bd

    def get_data(self, song_record):
        return self._get_data(song_record)


class FilesystemView(LibraryView):
    view_type = consts.VIEW_FILESYSTEM
    name = 'filesystem'
    label = _("Filesystem")
    def __init__(self, library):
        LibraryView.__init__(self, library)
        self.icon = self.folder_icon

    def get_crumb_data(self):
        path = self.config.wd.path
        crumbs = []
        if path and path != '/':
            parts = path.split('/')
        else:
            parts = [] # no crumbs for /
        # append a crumb for each part
        for i, part in enumerate(parts):
            partpath = '/'.join(parts[:i + 1])
            target = SongRecord(path=partpath)
            crumbs.append((part, Gtk.STOCK_OPEN, None, target))
        return crumbs

    def get_data_level(self, song_record):
        # Returns the number of directories down:
        if song_record.path == '/':
            # Every other path doesn't start with "/", so
            # start the level numbering at -1
            return -1
        else:
            return song_record.path.count("/")

    def _get_data(self, song_record):
        path = song_record.path
        # List all dirs/files at path
        if path == '/' and self.cache is not None:
            # Use cache if possible...
            return self.cache
        bd = []
        for file_info in self.library.mpd.lsinfo(path):
            if 'directory' in file_info:
                name = os.path.basename(file_info['directory'])
                dir_data = SongRecord(path=file_info["directory"])
                row_data = [self.folder_pixbuf, dir_data,
                            misc.escape_html(name),
                            self.TYPE_FOLDER]
                bd += [('d' + str(name).lower(), row_data)]
            elif 'file' in file_info:
                row_data = self.song_row(file_info)
                bd += [('f' + file_info['file'].lower(), row_data)]
        bd.sort(key=operator.itemgetter(0))
        if path == '/':
            self.cache = bd
        return bd


class AlbumView(LibraryView):
    view_type = consts.VIEW_ALBUM
    name = 'album'
    label = _("Albums")
    def __init__(self, library):
        LibraryView.__init__(self, library)
        self.icon = self.album_icon

    def get_crumb_data(self):
        # We don't want to show an artist button in album view
        keys = 'genre', 'album'
        nkeys = 2
        parts = (self.config.wd.genre, self.config.wd.album)
        return self._get_crumb_data(keys, nkeys, parts)

    def get_data(self, song_record):
        if song_record.album is None:
            return self._get_toplevel_data()
        return self._get_data(song_record)

    def _get_toplevel_data(self):
        if self.cache is not None:
            return self.cache
        albums = []
        untagged_found = False
        for album_info in self.library.mpd.listallinfo('/'):
            if 'file' in album_info and 'album' in album_info:
                album = album_info['album']
                artist = album_info.get('artist', NOTAG)
                year = album_info.get('date', NOTAG)
                path = self.library.get_multicd_album_root_dir(
                    os.path.dirname(album_info['file']))
                album_data = SongRecord(album=album, artist=artist,
                                        year=year, path=path)
                albums.append(album_data)
                if album == NOTAG:
                    untagged_found = True
        if not untagged_found:
            albums.append(SongRecord(album=NOTAG))
        albums = misc.remove_list_duplicates(albums, case=False)
        albums = list_mark_various_artists_albums(albums)
        bd = []
        for album_data in albums:
            playtime, num_songs = self.search.get_count(album_data)
            if num_songs > 0:
                display = misc.escape_html(album_data.album)
                disp_str = " <span weight='light'>({meta_strs})</span>"
                meta_strs = []
                artist, year = album_data.artist, album_data.year
                if artist and len(artist) > 0 and artist != NOTAG:
                    meta_strs.append(artist)
                if year and len(year) > 0 and year != NOTAG:
                    meta_strs.append(year)
                if len(meta_strs):
                    display += disp_str.format(meta_strs=", ".join(meta_strs))
                display += self.add_display_info(num_songs, playtime)
                row_data = [self.album_pixbuf, album_data, display,
                            self.TYPE_ALBUM]
                bd += [(misc.lower_no_the(album_data.album), row_data)]
        bd.sort(key=lambda key: locale.strxfrm(key[0]))
        for album in bd:
            data = album[1][1]
            cache_key = SongRecord(artist=data.artist, album=data.album,
                                   path=data.path)
            pb = self.artwork.get_album_row_pixbuf(cache_key)
            if pb:
                album[1][0] = pb
        self.cache = bd
        return bd


class ArtistView(LibraryView):
    view_type = consts.VIEW_ARTIST
    name = 'artist'
    label = _("Artists")
    def __init__(self, library):
        LibraryView.__init__(self, library)
        self.icon = self.artist_icon

    def get_parent(self, wd):
        if wd.album is not None:
            return SongRecord(artist=wd.artist)
        return self._get_parent(wd)

    def get_data(self, song_record):
        if song_record.artist is None and song_record.album is None:
            return self._get_toplevel_data()
        return self._get_data(song_record)

    def _get_toplevel_data(self):
        if self.cache is not None:
            return self.cache
        artists = self.search.get_list_items('artist', SongRecord())
        if not (NOTAG in artists):
            artists.append(NOTAG)
        bd = []
        for artist in artists:
            artist_data = SongRecord(artist=artist)
            playtime, num_songs = self.search.get_count(artist_data)
            if num_songs > 0:
                display = misc.escape_html(artist)
                display += self.add_display_info(num_songs, playtime)
                row_data = [self.artist_pixbuf, artist_data, display,
                            self.TYPE_ARTIST]
                bd += [(misc.lower_no_the(artist), row_data)]
        bd.sort(key=lambda key: locale.strxfrm(key[0]))
        self.cache = bd
        return bd


class GenreView(LibraryView):
    view_type = consts.VIEW_GENRE
    name = 'genre'
    label = _("Genres")
    def __init__(self, library):
        LibraryView.__init__(self, library)
        self.icon = self.genre_icon

    def get_parent(self, wd):
        path = "/"
        artist = None
        genre = None

        if wd.album is not None:
            genre, artist = (wd.genre, wd.artist)
            path = None
        elif wd.artist is not None:
            genre = wd.genre
            path = None
        else:
            return self._get_parent(wd)

        return SongRecord(path=path, artist=artist, genre=genre)

    def get_data(self, song_record):
        if song_record.genre is None:
            return self._get_toplevel_data()
        return self._get_data(song_record)

    def _get_toplevel_data(self):
        if self.cache is not None:
            return self.cache
        genres = self.search.get_list_items('genre', SongRecord())
        if not (NOTAG in genres):
            genres.append(NOTAG)
        bd = []
        for genre in genres:
            genre_data = SongRecord(genre=genre)
            playtime, num_songs = self.search.get_count(genre_data)
            if num_songs > 0:
                display = misc.escape_html(genre)
                display += self.add_display_info(num_songs, playtime)
                row_data = [self.genre_pixbuf, genre_data, display,
                            self.TYPE_GENRE]
                bd += [(misc.lower_no_the(genre), row_data)]
        bd.sort(key=lambda key: locale.strxfrm(key[0]))
        self.cache = bd
        return bd


class Library:
    def __init__(self, config, mpd, artwork, TAB_LIBRARY, settings_save,
                 filter_key_pressed, on_add_item, connected,
                 on_library_button_press, add_tab, get_multicd_album_root_dir):
        self.artwork = artwork
        self.config = config
        self.mpd = mpd
        self.menu = None # cyclic dependency, set later
        self.settings_save = settings_save
        self.filter_key_pressed = filter_key_pressed
        self.on_add_item = on_add_item
        self.connected = connected
        self.on_library_button_press = on_library_button_press
        self.get_multicd_album_root_dir = get_multicd_album_root_dir

        self.search_update_timeout = None
        self.search_condition = None

        self.save_timeout = None
        self.search_last_tooltip = None

        # Library tab
        self.builder = ui.builder('library')
        self.css_provider = ui.css_provider('library')

        self.vbox = self.builder.get_object('library_page_v_box')
        self.tree = self.builder.get_object('library_page_treeview')
        self.selection = self.tree.get_selection()
        self.breadcrumbs = self.builder.get_object('library_crumbs_box')
        self.crumb_section = self.builder.get_object(
            'library_crumb_section_togglebutton')
        self.crumb_section_image = self.builder.get_object(
            'library_crumb_section_image')
        crumb_break = self.builder.get_object('library_crumb_break_box')
        self.breadcrumbs.set_crumb_break(crumb_break)
        self.crumb_section_handler = None
        self.search_combo = self.builder.get_object(
            'library_page_searchbox_combo')
        self.search_text = self.builder.get_object(
            'library_page_searchbox_entry')
        self.search_button = self.builder.get_object(
            'library_page_searchbox_button')
        self.search_button.hide()
        self.view_menu_button = self.builder.get_object('library_crumb_button')
        tab_label_widget = self.builder.get_object('library_tab_eventbox')
        tab_label = self.builder.get_object('library_tab_label')
        tab_label.set_text(TAB_LIBRARY)

        self.tab = add_tab(self.vbox, tab_label_widget, TAB_LIBRARY, self.tree)

        self.search = LibrarySearch(self.mpd)
        self.search_thread = None

        self.album_crumb = None
        self.views = {}
        self.ACTION_TO_VIEW = {}
        for view in (FilesystemView(self), AlbumView(self), ArtistView(self),
                     GenreView(self),):
            self.views[view.view_type] = view
            self.ACTION_TO_VIEW[view.get_action_name()] = view

        self.view_caches_reset()
        self.view = self.views[self.config.lib_view]

        self.tree.connect('row_activated', self.on_row_activated)
        self.tree.connect('button_press_event',
                             self.on_library_button_press)
        self.tree.connect('key-press-event', self.on_key_press)
        self.tree.connect('query-tooltip', self.on_query_tooltip)
        self.view_menu_button.connect('clicked', self.view_popup)
        self.search_text.connect('key-press-event', self.on_search_key_pressed)
        self.search_text.connect('activate', self.on_search_enter)
        self.search_button.connect('clicked', self.on_search_end)

        self.artwork.art_thread.connect('art_ready', self.art_ready_cb)

        self.search_changed_handler = self.search_text.connect(
            'changed', self.on_search_update)
        searchcombo_changed_handler = self.search_combo.connect(
            'changed', self.on_search_combo_change)

        # Initialize library data and widget
        self.tree_position = {}
        self.tree_selected_path = {}
        self.search_combo.handler_block(searchcombo_changed_handler)
        self.search_combo.set_active(self.config.last_search_num)
        self.search_combo.handler_unblock(searchcombo_changed_handler)
        self.tree_data = Gtk.ListStore(GdkPixbuf.Pixbuf,
                                         GObject.TYPE_PYOBJECT, str, str)
        self.tree.set_model(self.tree_data)
        self.tree.set_search_column(2)
        data_cell = Gtk.CellRendererText()
        data_cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        img_cell = Gtk.CellRendererPixbuf()
        self.column = Gtk.TreeViewColumn()
        self.column.pack_start(img_cell, False)
        self.column.pack_start(data_cell, True)
        self.column.add_attribute(img_cell, 'pixbuf', 0)
        self.column.add_attribute(data_cell, 'markup', 2)
        self.column.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        self.tree.append_column(self.column)
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)

    def get_actions(self):
        return [view.get_action(self.on_view_chosen)
            for view in self.views.values()]

    def get_model(self):
        return self.tree_data

    def get_widgets(self):
        return self.vbox

    def get_treeview(self):
        return self.tree

    def get_selection(self):
        return self.selection

    def set_menu(self, menu):
        self.menu = menu
        self.menu.attach_to_widget(self.view_menu_button, None)

    def view_popup(self, button):
        self.menu.popup(None, None, self.get_popup_position, button, 1, 0)

    def get_popup_position(self, _menu, button):
        alloc = button.get_allocation()
        return (self.config.x + alloc.x,
                self.config.y + alloc.y + alloc.height,
                True)

    def on_view_chosen(self, action):
        self.on_search_end(None)
        self.view = self.ACTION_TO_VIEW[action.get_name()]
        self.config.lib_view = self.view.view_type
        self.tree.grab_focus()
        self.tree_position = {}
        self.tree_selected_path = {}
        self.browse(root=SongRecord(path="/"))
        self.selection.unselect_all()
        GLib.idle_add(self.tree.scroll_to_point, 0, 0)

    def view_caches_reset(self):
        # We should call this on first load and whenever mpd is
        # updated.
        for view in self.views.values():
            view.invalidate_cache()
        self.search.invalidate_cache()

    def browse(self, _widget=None, root=None):
        # Populates the library list with entries
        if not self.connected():
            return
        # FIXME kill any search here

        default_path = SongRecord(path="/")
        active_is_filesystem = self.config.lib_view == consts.VIEW_FILESYSTEM
        wd = self.config.wd

        # Ensure root
        if root is None or (active_is_filesystem and root.path is None):
            root = default_path
        # Ensure wd
        if wd is None or (active_is_filesystem and wd.path is None):
            self.config.wd = wd = default_path

        prev_selection = []
        prev_selection_root = False
        prev_selection_parent = False
        if root == wd:
            # This will happen when the database is updated. So, lets save
            # the current selection in order to try to re-select it after
            # the update is over.
            model, selected = self.selection.get_selected_rows()
            for path in selected:
                prev_selection.append(model.get_value(model.get_iter(path), 1))
            self.tree_position[wd] = self.tree.get_visible_rect().height
            path_updated = True
        else:
            path_updated = False

        new_level = self.view.get_data_level(root)
        curr_level = self.view.get_data_level(wd)
        # The logic below is more consistent with, e.g., thunar.
        if new_level > curr_level:
            # Save position and row for where we just were if we've
            # navigated into a sub-directory:
            self.tree_position[wd] = self.tree.get_visible_rect().height
            model, rows = self.selection.get_selected_rows()
            if len(rows) > 0:
                self.tree_selected_path[wd] = rows[0]
        elif active_is_filesystem and (root != wd or new_level != curr_level):
            # If we've navigated to a parent directory, don't save
            # anything so that the user will enter that subdirectory
            # again at the top position with nothing selected
            self.tree_position[wd] = 0
            self.tree_selected_path[wd] = None

        # In case sonata is killed or crashes, we'll save the library state
        # in 5 seconds (first removing any current settings_save timeouts)
        if wd != root:
            try:
                GLib.source_remove(self.save_timeout)
            except:
                pass
            self.save_timeout = GLib.timeout_add(5000, self.settings_save)

        self.config.wd = wd = root
        self.tree.freeze_child_notify()
        self.tree_data.clear()
        self.view.invalidate_row_cache()

        # Populate treeview with data:
        bd = []
        while len(bd) == 0:
            bd = self.view.get_data(wd)

            if len(bd) == 0:
                # Nothing found; go up a level until we reach the top level
                # or results are found
                self.config.wd = self.view.get_parent(self.config.wd)
                if self.config.wd == wd:
                    break
                wd = self.config.wd

        for index, (_sort, path) in enumerate(bd):
            self.tree_data.append(path)
            data = path[1]
            cache_key = SongRecord(artist=data.artist, album=data.album,
                                   path=data.path)
            if cache_key in self.artwork.cache:
                pb = self.artwork.get_album_row_pixbuf(cache_key)
                if pb:
                    self.set_pb_for_row(index, pb)
                
            self.view.data_rows[cache_key] = index

        self.tree.thaw_child_notify()

        # Scroll back to set view for current dir:
        self.tree.realize()
        GLib.idle_add(self.set_view, not path_updated)
        if (len(prev_selection) > 0 or prev_selection_root or
                prev_selection_parent):
            # Retain pre-update selection:
            self.retain_selection(prev_selection, prev_selection_root,
                                          prev_selection_parent)

        self.update_breadcrumbs()

    def set_pb_for_row(self, row, pb):
        i = self.tree_data.get_iter((row,))
        self.tree_data.set_value(i, 0, pb)

    def pixbuf_for_album_crumb(self, data=None, force=False):
        if self.album_crumb:
            cache_data = SongRecord(artist=self.config.wd.artist,
                                    album=self.config.wd.album,
                                    path=self.config.wd.path)
            if force or cache_data == data:
                pb = self.artwork.get_album_row_pixbuf(cache_data)
                if pb:
                    pb = pb.scale_simple(16, 16, GdkPixbuf.InterpType.HYPER)
                    self.album_crumb.image.set_from_pixbuf(pb)

    def art_ready_cb(self, widget, data):
        self.pixbuf_for_album_crumb(data)
        if not data in self.view.data_rows:
            return
        pb = self.artwork.get_album_row_pixbuf(data)
        if pb:
            # lookup for existing row
            row = self.view.data_rows[data]
            self.set_pb_for_row(row, pb)

    def update_breadcrumbs(self):
        # remove previous buttons
        for b in self.breadcrumbs:
            self.breadcrumbs.remove(b)

        label = self.view.label

        # the first crumb is the root of the current view
        self.crumb_section.set_label(label)
        self.crumb_section_image.set_from_stock(self.view.icon,
                                                Gtk.IconSize.MENU)
        self.crumb_section.set_tooltip_text(label)
        if self.crumb_section_handler:
            self.crumb_section.disconnect(self.crumb_section_handler)

        self.album_crumb = None
        crumbs = self.view.get_crumb_data()

        if not len(crumbs):
            self.crumb_section.set_active(True)
            context = self.crumb_section.get_style_context()
            context.add_class('last_crumb')
        else:
            self.crumb_section.set_active(False)
            context = self.crumb_section.get_style_context()
            context.remove_class('last_crumb')

        self.crumb_section_handler = self.crumb_section.connect('toggled',
            self.browse, SongRecord(path='/'))

        # add a button for each crumb
        for crumb in crumbs:
            text, icon, pb, target = crumb
            text = misc.escape_html(text)
            label = Gtk.Label(text, use_markup=True)

            if icon:
                image = Gtk.Image.new_from_stock(icon, Gtk.IconSize.MENU)
            elif pb:
                pb = pb.scale_simple(16, 16, GdkPixbuf.InterpType.HYPER)
                image = Gtk.Image.new_from_pixbuf(pb)

            b = breadcrumbs.CrumbButton(image, label)

            if icon == 'sonata-album':
                self.album_crumb = b
                self.pixbuf_for_album_crumb(force=True)

            if crumb is crumbs[-1]:
                # FIXME makes the button request minimal space:
                b.set_active(True)
                context = b.get_style_context()
                context.add_class('last_crumb')

            b.set_tooltip_text(label.get_label())
            b.connect('toggled', self.browse, target)
            self.breadcrumbs.pack_start(b, False, False, 0)
            b.show_all()

    def retain_selection(self, prev_selection, prev_selection_root,
                         prev_selection_parent):
        self.selection.unselect_all()
        # Now attempt to retain the selection from before the update:
        for value in prev_selection:
            for row in self.tree_data:
                if value == row[1]:
                    self.selection.select_path(row.path)
                    break
        if prev_selection_root:
            self.selection.select_path((0,))
        if prev_selection_parent:
            self.selection.select_path((1,))

    def set_view(self, select_items=True):
        # select_items should be false if the same directory has merely
        # been refreshed (updated)
        try:
            if self.config.wd in self.tree_position:
                self.tree.scroll_to_point(
                    -1, self.tree_position[self.config.wd])
            else:
                self.tree.scroll_to_point(0, 0)
        except:
            self.tree.scroll_to_point(0, 0)

        # Select and focus previously selected item
        if select_items:
            if self.config.wd in self.tree_selected_path:
                try:
                    if self.tree_selected_path[self.config.wd]:
                        self.selection.select_path(
                            self.tree_selected_path[self.config.wd])
                        self.tree.grab_focus()
                except:
                    pass

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.keyval_from_name('Return'):
            self.on_row_activated(widget, widget.get_cursor()[0])
            return True

    def on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        if keyboard_mode or not self.search_visible():
            widget.set_tooltip_text("")
            return False

        bin_x, bin_y = widget.convert_widget_to_bin_window_coords(x, y)

        pathinfo = widget.get_path_at_pos(bin_x, bin_y)
        if not pathinfo:
            widget.set_tooltip_text("")
            # If the user hovers over an empty row and then back to
            # a row with a search result, this will ensure the tooltip
            # shows up again:
            GLib.idle_add(self.search_tooltips_enable, widget, x, y,
                          keyboard_mode, None)
            return False
        treepath, _col, _x2, _y2 = pathinfo

        i = self.tree_data.get_iter(treepath.get_indices()[0])
        path = misc.escape_html(self.tree_data.get_value(i, 1).path)
        song = self.tree_data.get_value(i, 2)
        new_tooltip = "<b>%s:</b> %s\n<b>%s:</b> %s" \
                % (_("Song"), song, _("Path"), path)

        if new_tooltip != self.search_last_tooltip:
            self.search_last_tooltip = new_tooltip
            self.tree.set_property('has-tooltip', False)
            GLib.idle_add(self.search_tooltips_enable, widget, x, y,
                          keyboard_mode, tooltip)
            GLib.idle_add(widget.set_tooltip_markup, new_tooltip)
            return

        self.search_last_tooltip = new_tooltip

        return False #api says we should return True, but this doesn't work?

    def search_tooltips_enable(self, widget, x, y, keyboard_mode, tooltip):
        self.tree.set_property('has-tooltip', True)
        if tooltip is not None:
            self.on_query_tooltip(widget, x, y, keyboard_mode, tooltip)

    def on_row_activated(self, _widget, path, _column=0):
        if path is None:
            # Default to last item in selection:
            _model, selected = self.selection.get_selected_rows()
            if len(selected) >= 1:
                path = selected[0]
            else:
                return
        row_iter = self.tree_data.get_iter(path)
        value = self.tree_data.get_value(row_iter, 1)
        row_type = self.tree_data.get_value(row_iter, 3)
        if row_type == self.view.TYPE_SONG:
            # Song found, add item
            self.on_add_item(self.tree)
        else:
            self.browse(None, value)

    def on_browse_parent(self):
        if not self.search_visible():
            if self.tree.is_focus():
                value = self.view.get_parent(self.config.wd)
                self.browse(None, value)
                return True

    def get_path_child_filenames(self, return_root):
        # If return_root=True, return main directories whenever possible
        # instead of individual songs in order to reduce the number of
        # mpd calls we need to make. We won't want this behavior in some
        # instances, like when we want all end files for editing tags
        items = []
        model, rows = self.selection.get_selected_rows()
        for path in rows:
            row_iter = model.get_iter(path)
            data = model.get_value(row_iter, 1)
            value = model.get_value(row_iter, 2)
            row_type = model.get_value(row_iter, 3)
            meta_parts = [data.album, data.artist, data.year, data.genre]
            meta = any([part is None for part in meta_parts])
            if data.path is not None and not any(meta_parts):
                if row_type == self.view.TYPE_SONG:
                    # File
                    items.append(data.path)
                elif not return_root:
                    # Directory without root
                    items += self.get_path_files_recursive(data.path)
                else:
                    # Full Directory
                    items.append(data.path)
            else:
                results, _playtime, _num_songs = self.search.get_search_items(
                    data)
                for item in results:
                    items.append(item.file)
        # Make sure we don't have any EXACT duplicates:
        items = misc.remove_list_duplicates(items, case=True)
        return items

    def get_path_files_recursive(self, path):
        results = []
        for item in self.mpd.lsinfo(path):
            if 'directory' in item:
                results = results + self.get_path_files_recursive(
                    item['directory'])
            elif 'file' in item:
                results.append(item['file'])
        return results

    def on_search_combo_change(self, _combo=None):
        self.config.last_search_num = self.search_combo.get_active()
        if not self.search_visible():
            return
        self.on_search_update()

    def on_search_update(self, _widget=None):
        if not self.search_visible():
            self.search_toggle(None)
        # Only update the search if 300ms pass without a change in Gtk.Entry
        try:
            GLib.source_remove(self.search_update_timeout)
        except:
            pass
        self.search_update_timeout = GLib.timeout_add(300, self.update_search)

    def update_search(self):
        self.search_update_timeout = None
        with self.search_condition:
            self.search.search_num = self.config.last_search_num
            self.search.search_input = self.search_text.get_text()
            self.search_condition.notify_all()

    def on_search_end(self, _button, move_focus=True):
        if self.search_visible():
            self.search_toggle(move_focus)

    def search_visible(self):
        return self.search_button.get_property('visible')

    def search_toggle(self, move_focus):
        if not self.search_visible() and self.connected():
            self.tree.set_property('has-tooltip', True)
            ui.show(self.search_button)
            self.search_condition = threading.Condition()
            self.search_thread = LibrarySearchThread(self.search,
                                                     self.search_condition)
            self.search_thread.connect('search_ready', self.search_ready_cb)
            self.search_thread.connect('search_stopped', self.on_search_end)
            self.search_thread.start()
        else:
            ui.hide(self.search_button)
            self.search_text.handler_block(self.search_changed_handler)
            self.search_text.set_text("")
            self.search_text.handler_unblock(self.search_changed_handler)
            self.search_thread.stop()
            with self.search_condition:
                self.search_condition.notify_all()
            self.search_thread.join()
            self.search_thread = None
            self.search_condition = None
            self.search.cleanup_search()
            # Restore the regular view
            GLib.idle_add(self.browse, None, self.config.wd)
            GLib.idle_add(ui.reset_entry_marking, self.search_text)
            if move_focus:
                self.tree.grab_focus()

    def search_ready_cb(self, _widget, data):
        # FIXME kill any breadcrumb trail here (it should restore on search end
        # if the view doesn't change)
        bd = [self.view.song_row(song) for song in data if 'file' in song]
        bd.sort(key=lambda key: locale.strxfrm(key[2]))
        self.tree.freeze_child_notify()
        self.tree_data.clear()
        for row in bd:
            self.tree_data.append(row)
        self.tree.thaw_child_notify()
        if len(bd) == 0:
            GLib.idle_add(ui.set_entry_invalid, self.search_text)
        else:
            GLib.idle_add(self.tree.set_cursor, Gtk.TreePath.new_first(),
                          None, False)
            GLib.idle_add(ui.reset_entry_marking, self.search_text)

    def on_search_key_pressed(self, widget, event):
        self.filter_key_pressed(widget, event, self.tree)

    def on_search_enter(self, _entry):
        self.on_row_activated(None, None)

    def search_set_focus(self):
        GLib.idle_add(self.search_text.grab_focus)

