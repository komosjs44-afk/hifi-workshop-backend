"""A small MPD protocol server for tests, listening on 127.0.0.1 with a free port.

It models the parts of MPD 0.24 the adapter uses. Playback time does not advance on its own.
It is not a reference for MPD behaviour: docs/raspberry-pi-mpd-verification.md checks the real one.
"""
from __future__ import annotations

import socket
import socketserver
import threading

SONGS = [
    {"file": "test/sine-44k.wav", "duration": "10.000", "Format": "44100:16:2"},
    {"file": "test/sine-48k.wav", "duration": "12.500", "Format": "48000:24:2"},
    {"file": "albums/Quiet/01.flac", "Title": "Between the Tides", "Artist": "Northbound", "AlbumArtist": "Northbound",
     "Album": "Quiet Coordinates", "Date": "2024-03-01", "Track": "1/2", "duration": "248.2", "Format": "96000:24:2"},
    {"file": "albums/Quiet/02.flac", "Title": "Low Light", "Artist": "Northbound", "Artist2": "x", "AlbumArtist": "Northbound",
     "Album": "Quiet Coordinates", "Date": "2024", "Track": "2/2", "duration": "200.0", "Format": "96000:24:2"},
]


class MpdAck(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


def tokenize(line: str) -> list[str]:
    tokens, i = [], 0
    while i < len(line):
        if line[i] == " ":
            i += 1
        elif line[i] == '"':
            i, value = i + 1, []
            while line[i] != '"':
                if line[i] == "\\":
                    i += 1
                value.append(line[i])
                i += 1
            tokens.append("".join(value))
            i += 1
        else:
            end = line.find(" ", i)
            end = len(line) if end < 0 else end
            tokens.append(line[i:end])
            i = end
    return tokens


class FakeMpd:
    def __init__(self, songs: list[dict] | None = None):
        self.songs = [dict(song) for song in (songs or SONGS)]
        self.lock = threading.Lock()
        self.log: list[str] = []
        self.drop_next = 0  # close the connection instead of answering the next N commands
        self.status_error: str | None = None
        self.db_update = 1_700_000_000
        self.queue: list[tuple[int, dict]] = []
        self.next_id = 1
        self.state, self.current, self.elapsed, self.version = "stop", None, 0.0, 1
        self.connections = 0
        self._open: list[socket.socket] = []
        self._server: socketserver.ThreadingTCPServer | None = None

    # ---- lifecycle ----
    def start(self, port: int = 0) -> "FakeMpd":
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                fake.connections += 1
                fake._open.append(self.connection)
                self.wfile.write(b"OK MPD 0.24.4\n")
                batch: list[str] | None = None
                ok_list = False
                for raw in self.rfile:
                    line = raw.decode("utf-8").rstrip("\n")
                    if fake.drop_next:
                        fake.drop_next -= 1
                        return
                    if line in ("command_list_begin", "command_list_ok_begin"):
                        batch, ok_list = [], line == "command_list_ok_begin"
                        continue
                    if batch is not None and line != "command_list_end":
                        batch.append(line)
                        continue
                    commands, batch = (batch, None) if line == "command_list_end" else ([line], None)
                    if commands == ["close"]:
                        return
                    self.wfile.write(fake.run(commands, ok_list and len(commands) > 0 and line == "command_list_end").encode("utf-8"))

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", port), Handler)
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return self

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def shutdown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        for connection in self._open:  # like MPD exiting: clients see the connection close
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._open.clear()

    # ---- protocol ----
    def run(self, commands: list[str], list_ok: bool) -> str:
        out: list[str] = []
        with self.lock:
            for index, line in enumerate(commands):
                name, *args = tokenize(line)
                self.log.append(line)
                try:
                    out += [f"{key}: {value}" for key, value in getattr(self, "cmd_" + name, self.cmd_unknown)(*args)]
                except MpdAck as ack:
                    return "".join(f"{item}\n" for item in out) + f"ACK [{ack.code}@{index}] {{{name}}} {ack.message}\n"
                except (TypeError, ValueError):
                    return f"ACK [2@{index}] {{{name}}} wrong arguments\n"
                if list_ok:
                    out.append("list_OK")
        return "".join(f"{item}\n" for item in out) + "OK\n"

    def _pos(self, song_id: int) -> int:
        for pos, (item_id, _) in enumerate(self.queue):
            if item_id == song_id:
                return pos
        raise MpdAck(50, "No such song")

    def _song_pairs(self, song: dict) -> list[tuple[str, str]]:
        return [(key.rstrip("2"), value) for key, value in song.items()]

    def cmd_unknown(self, *args):
        raise MpdAck(5, "unknown command")

    def cmd_ping(self):
        return []

    def cmd_stats(self):
        return [("songs", str(len(self.songs))), ("db_update", str(self.db_update))]

    def cmd_status(self):
        pairs = [("volume", "-1"), ("repeat", "0"), ("random", "0"), ("single", "0"), ("consume", "0"),
                 ("playlist", str(self.version)), ("playlistlength", str(len(self.queue))), ("state", self.state)]
        if self.current is not None:
            pos = self._pos(self.current)
            pairs += [("song", str(pos)), ("songid", str(self.current))]
            if self.state != "stop":
                song = self.queue[pos][1]
                pairs += [("elapsed", f"{self.elapsed:.3f}"), ("duration", song["duration"]), ("audio", song["Format"])]
        if self.status_error:
            pairs.append(("error", self.status_error))
        return pairs

    def cmd_listallinfo(self):
        pairs = [("directory", "albums"), ("Last-Modified", "2026-11-01T00:00:00Z"), ("directory", "albums/Quiet")]
        for song in self.songs:
            pairs += self._song_pairs(song)
        return pairs + [("playlist", "favourites.m3u")]

    def cmd_playlistinfo(self):
        pairs = []
        for pos, (item_id, song) in enumerate(self.queue):
            pairs += self._song_pairs(song) + [("Pos", str(pos)), ("Id", str(item_id))]
        return pairs

    def _changed(self):
        self.version += 1

    def cmd_addid(self, uri, position=None):
        song = next((song for song in self.songs if song["file"] == uri), None)
        if song is None:
            raise MpdAck(50, "No such directory")
        pos = len(self.queue) if position is None else int(position)
        if not 0 <= pos <= len(self.queue):
            raise MpdAck(2, "Bad song index")
        item_id, self.next_id = self.next_id, self.next_id + 1
        self.queue.insert(pos, (item_id, song))
        self._changed()
        return [("Id", str(item_id))]

    def cmd_deleteid(self, song_id):
        pos = self._pos(int(song_id))
        del self.queue[pos]
        if self.current == int(song_id):
            # MPD continues with the following song while playing; otherwise the selection is lost.
            if self.state != "stop" and pos < len(self.queue):
                self.current, self.elapsed = self.queue[pos][0], 0.0
            else:
                self.current, self.state, self.elapsed = None, "stop", 0.0
        self._changed()
        return []

    def cmd_moveid(self, song_id, to):
        pos, to = self._pos(int(song_id)), int(to)
        if not 0 <= to < len(self.queue):
            raise MpdAck(2, "Bad song index")
        self.queue.insert(to, self.queue.pop(pos))
        self._changed()
        return []

    def cmd_clear(self):
        self.queue, self.current, self.state, self.elapsed = [], None, "stop", 0.0
        self._changed()
        return []

    def cmd_playid(self, song_id=None):
        if song_id is not None:
            self._pos(int(song_id))
            self.current = int(song_id)
        self.state, self.elapsed = "play", 0.0
        return []

    def cmd_pause(self, value=None):
        if self.state == "stop":
            return []
        if value is None:
            self.state = "pause" if self.state == "play" else "play"
        else:
            self.state = "pause" if value == "1" else "play"
        return []

    def cmd_stop(self):
        self.state, self.elapsed = "stop", 0.0
        return []

    def cmd_next(self):
        raise MpdAck(5, "the adapter must not rely on next")

    cmd_previous = cmd_next

    def cmd_seekcur(self, seconds):
        if self.state == "stop":
            raise MpdAck(55, "Not playing")
        self.elapsed = float(seconds)
        return []

    def cmd_seekid(self, song_id, seconds):
        self._pos(int(song_id))
        self.current, self.elapsed, self.state = int(song_id), float(seconds), "play" if self.state == "stop" else self.state
        return []

    # ---- helpers for tests ----
    def fill(self, *uris: str) -> list[int]:
        with self.lock:
            return [int(self.cmd_addid(uri)[0][1]) for uri in uris]
