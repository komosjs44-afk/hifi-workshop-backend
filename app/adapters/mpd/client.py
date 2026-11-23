"""Minimal client for the MPD text protocol (https://mpd.readthedocs.io/en/latest/protocol.html).

Only what the audio engine needs: one TCP connection, plain commands and command lists.
Standard library only, so the Raspberry Pi needs no extra package.
"""
from __future__ import annotations

import socket

Pairs = list[tuple[str, str]]
Command = tuple[str, ...]

# A reused connection that fails with one of these was closed on the other side (MPD drops idle
# clients after `connection_timeout`). The command never reached MPD, so it is safe to resend.
_DEAD_CONNECTION = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


class MpdConnectionError(Exception):
    """MPD could not be reached, or the connection broke during a command."""


class MpdProtocolError(Exception):
    """MPD answered `ACK [code@index] {command} message`."""

    def __init__(self, code: int, index: int, command: str, message: str):
        super().__init__(f"[{code}@{index}] {{{command}}} {message}")
        self.code, self.index, self.command, self.message = code, index, command, message


class _ClosedByPeer(Exception):
    pass


def quote(argument: str) -> str:
    if any(char in argument for char in "\r\n\0"):
        raise ValueError("MPD arguments cannot contain line breaks or NUL characters.")
    return '"' + argument.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_ack(line: str) -> MpdProtocolError:
    # ACK [50@0] {playid} No such song
    head, _, message = line[5:].partition("] ")
    code, _, index = head.partition("@")
    command, _, message = message.partition("} ")
    return MpdProtocolError(int(code), int(index), command.lstrip("{"), message)


class MpdClient:
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.server_version: str | None = None
        self.generation = 0  # grows with every new connection; cached MPD state is invalid after a reconnect
        self._socket: socket.socket | None = None
        self._reader = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = self._reader = None

    def _connect(self) -> None:
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._reader = self._socket.makefile("rb")
            greeting = self._readline()
        except (OSError, _ClosedByPeer) as error:
            self.close()
            raise MpdConnectionError(f"cannot connect to MPD at {self.address}: {error or 'connection closed'}") from error
        if not greeting.startswith("OK MPD "):
            self.close()
            raise MpdConnectionError(f"{self.address} did not answer like MPD: {greeting[:80]!r}")
        self.server_version = greeting[7:]
        self.generation += 1

    def _readline(self) -> str:
        line = self._reader.readline()
        if not line:
            raise _ClosedByPeer("connection closed by MPD")
        return line.decode("utf-8", errors="replace").rstrip("\n")

    def _read_response(self, parts: int) -> list[Pairs]:
        """Read `parts` answers separated by `list_OK` and closed by `OK`."""
        responses: list[Pairs] = [[]]
        while True:
            line = self._readline()
            if line == "OK":
                return responses
            if line.startswith("ACK "):
                raise _parse_ack(line)
            if line == "list_OK":
                if len(responses) < parts:
                    responses.append([])
                continue
            key, _, value = line.partition(": ")
            responses[-1].append((key, value))

    def execute(self, commands: list[Command]) -> list[Pairs]:
        """Run one command, or several as an atomic command list. Returns one pair list per command."""
        lines = [" ".join([name, *map(quote, args)]) for name, *args in commands]
        if len(lines) > 1:
            lines = ["command_list_ok_begin", *lines, "command_list_end"]
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        for attempt in (1, 2):
            reused = self._socket is not None
            if not reused:
                self._connect()
            try:
                self._socket.sendall(payload)
                return self._read_response(len(commands))
            except MpdProtocolError:
                raise
            except (*_DEAD_CONNECTION, _ClosedByPeer) as error:
                self.close()
                if reused and attempt == 1:
                    continue
                raise MpdConnectionError(f"connection to MPD at {self.address} was lost: {error}") from error
            except OSError as error:  # timeouts included: the command may have run, so it is not resent
                self.close()
                raise MpdConnectionError(f"MPD at {self.address} did not answer: {error or type(error).__name__}") from error
        raise AssertionError("unreachable")

    def command(self, name: str, *args: str) -> Pairs:
        return self.execute([(name, *args)])[0]
