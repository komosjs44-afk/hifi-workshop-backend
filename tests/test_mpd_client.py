import socket
import threading

import pytest

from app.adapters.mpd.client import MpdClient, MpdConnectionError, MpdProtocolError, quote

from .conftest import free_port
from .fake_mpd import tokenize


def test_quote_escapes_and_round_trips():
    for value in ('plain', 'with space', 'quote " inside', 'back\\slash', 'Ünïcode/폴더/곡.flac'):
        assert tokenize(f"cmd {quote(value)}") == ["cmd", value]


@pytest.mark.parametrize("value", ["a\nstatus", "a\rb", "a\0b"])
def test_quote_rejects_line_breaks(value):
    with pytest.raises(ValueError):
        quote(value)


def test_connects_lazily_and_reads_the_version(fake_mpd):
    client = MpdClient("127.0.0.1", fake_mpd.port)
    assert fake_mpd.connections == 0
    assert client.command("ping") == []
    assert client.server_version == "0.24.4" and client.generation == 1


def test_command_list_returns_one_answer_per_command(fake_mpd):
    fake_mpd.fill("test/sine-44k.wav")
    client = MpdClient("127.0.0.1", fake_mpd.port)
    status, queue, ping = client.execute([("status",), ("playlistinfo",), ("ping",)])
    assert ("playlistlength", "1") in status and ("file", "test/sine-44k.wav") in queue and ping == []
    assert fake_mpd.log[-3:] == ["status", "playlistinfo", "ping"]


def test_ack_becomes_a_protocol_error_and_keeps_the_connection(fake_mpd):
    client = MpdClient("127.0.0.1", fake_mpd.port)
    with pytest.raises(MpdProtocolError) as error:
        client.command("playid", "99")
    assert (error.value.code, error.value.index, error.value.command, error.value.message) == (50, 0, "playid", "No such song")
    client.command("ping")
    assert fake_mpd.connections == 1


def test_ack_inside_a_command_list_reports_the_failing_index(fake_mpd):
    client = MpdClient("127.0.0.1", fake_mpd.port)
    with pytest.raises(MpdProtocolError) as error:
        client.execute([("ping",), ("deleteid", "7")])
    assert (error.value.index, error.value.command) == (1, "deleteid")


def test_reconnects_once_when_mpd_closed_the_idle_connection(fake_mpd):
    client = MpdClient("127.0.0.1", fake_mpd.port)
    client.command("ping")
    fake_mpd.drop_next = 1  # like MPD's connection_timeout closing an idle client
    assert ("state", "stop") in client.command("status")
    assert fake_mpd.connections == 2 and client.generation == 2


def test_gives_up_when_the_new_connection_fails_too(fake_mpd):
    client = MpdClient("127.0.0.1", fake_mpd.port)
    client.command("ping")
    fake_mpd.drop_next = 2
    with pytest.raises(MpdConnectionError):
        client.command("status")


def test_connection_refused():
    client = MpdClient("127.0.0.1", free_port(), timeout=0.2)
    with pytest.raises(MpdConnectionError, match="cannot connect"):
        client.command("ping")


def test_rejects_a_server_that_is_not_mpd():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def answer():
        connection, _ = listener.accept()
        connection.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        connection.close()

    threading.Thread(target=answer, daemon=True).start()
    try:
        with pytest.raises(MpdConnectionError, match="did not answer like MPD"):
            MpdClient("127.0.0.1", listener.getsockname()[1], timeout=1).command("ping")
    finally:
        listener.close()


def test_timeout_on_a_reused_connection_is_not_resent():
    """A timed-out command may have run in MPD, so resending it could add a song twice."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    accepted = []

    def answer_once_then_hang():
        connection, _ = listener.accept()
        accepted.append(connection)
        connection.sendall(b"OK MPD 0.24.4\n")
        connection.recv(100)
        connection.sendall(b"OK\n")

    threading.Thread(target=answer_once_then_hang, daemon=True).start()
    client = MpdClient("127.0.0.1", listener.getsockname()[1], timeout=0.3)
    try:
        client.command("ping")
        with pytest.raises(MpdConnectionError, match="did not answer"):
            client.command("addid", "x")
        listener.setblocking(False)
        with pytest.raises(BlockingIOError):
            listener.accept()  # no second connection was opened
    finally:
        for connection in accepted:
            connection.close()
        listener.close()
