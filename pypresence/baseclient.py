from __future__ import annotations

import inspect
import inspect
import json
import struct
import sys
import threading
import ctypes

# TODO: Get rid of this import * lol
from .exceptions import (
    ConnectionTimeout,
    DiscordError,
    DiscordNotFound,
    InvalidArgument,
    InvalidID,
    InvalidPipe,
    PipeClosed,
    PyPresenceException,
    ResponseTimeout,
    ServerError,
)
from .payloads import Payload
from .utils import get_event_loop, get_ipc_path


class BaseClient:

    def __init__(self, client_id: str, **kwargs):
        loop = kwargs.get("loop", None)
        handler = kwargs.get("handler", None)
        self.pipe = kwargs.get("pipe", None)
        self.isasync = kwargs.get("isasync", False)
        self.connection_timeout = kwargs.get("connection_timeout", 30)
        self.response_timeout = kwargs.get("response_timeout", 10)

        client_id = str(client_id)

        if loop is not None:
            self.update_event_loop(loop)
        else:
            self.update_event_loop(get_event_loop())

        # Readers/writers are plain objects implementing `read` and `write`.
        self.sock_reader = None
        self.sock_writer = None

        self.client_id = client_id

        if handler is not None:
            if not inspect.isfunction(handler):
                raise PyPresenceException("Error handler must be a function.")
            args = inspect.getfullargspec(handler).args
            if args[0] == "self":
                args = args[1:]
            if len(args) != 2:
                raise PyPresenceException(
                    "Error handler should only accept two arguments."
                )

            if self.isasync:
                if not inspect.iscoroutinefunction(handler):
                    raise InvalidArgument(
                        "Coroutine",
                        "Subroutine",
                        "You are running async mode - "
                        "your error handler should be awaitable.",
                    )
                err_handler = self._async_err_handle
            else:
                err_handler = self._err_handle

            # asyncio has been removed; if a loop object was provided it may
            # expose `set_exception_handler`. Only call if present.
            if getattr(self.loop, "set_exception_handler", None):
                self.loop.set_exception_handler(err_handler)
            self.handler = handler

        if getattr(self, "on_event", None):  # Tasty bad code ;^)
            self._events_on = True
        else:
            self._events_on = False

    def update_event_loop(self, loop):
        # noinspection PyAttributeOutsideInit
        self.loop = loop
        # No-op for non-asyncio environment


    def _err_handle(self, loop, context: dict):
        # Synchronous error handler invocation
        self.handler(context["exception"], context.get("future"))

    # noinspection PyUnusedLocal
    def _async_err_handle(self, loop, context: dict):
        # If an async handler was provided but we're running without asyncio,
        # attempt to run it if the loop provides a `run_until_complete` method.
        coro = self.handler(context["exception"], context.get("future"))
        if getattr(self.loop, "run_until_complete", None):
            self.loop.run_until_complete(coro)
        else:
            # Can't run coroutine; raise to notify user.
            raise InvalidArgument(
                "Coroutine",
                "Subroutine",
                "Async handler provided but no event loop is available.",
            )

    def read_output(self):
        try:
            preamble = self.sock_reader.read(8)
            status_code, length = struct.unpack("<II", preamble[:8])
            data = self.sock_reader.read(length)
        except (BrokenPipeError, struct.error):
            raise PipeClosed
        payload = json.loads(data.decode("utf-8"))
        if payload["evt"] == "ERROR":
            raise ServerError(payload["data"]["message"])
        return payload

    def send_data(self, op: int, payload: dict | Payload):
        if isinstance(payload, Payload):
            payload = payload.data
        payload_string = json.dumps(payload)

        assert (
            self.sock_writer is not None
        ), "You must connect your client before sending events!"

        self.sock_writer.write(
            struct.pack("<II", op, len(payload_string)) + payload_string.encode("utf-8")
        )

    def create_reader_writer(self, ipc_path):
        try:
            if sys.platform in ("linux", "darwin"):
                # Use UNIX socket connection to the IPC path
                import socket

                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(self.connection_timeout)
                client.connect(ipc_path)
                # Wrap socket with simple reader/writer objects
                self.sock_reader = _SocketReader(client)
                self.sock_writer = _SocketWriter(client)
            elif sys.platform == "win32":
                self.sock_reader, self.sock_writer = self._create_named_pipe(ipc_path)
        except FileNotFoundError:
            raise InvalidPipe
        except socket.timeout:
            raise ConnectionTimeout
        
    def _create_named_pipe(self, ipc_path):
        pipe_name = r'\\.\pipe\{}'.format(ipc_path)
        try:
            # Create the named pipe
            handle = ctypes.windll.kernel32.CreateNamedPipeW(
                pipe_name,
                0x00000003,  # PIPE_ACCESS_DUPLEX
                0x00000000,  # PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT
                1,           # Number of instances
                512,         # Output buffer size
                512,         # Input buffer size
                0,           # Client time-out
                None         # Default security attributes
            )
            if handle == -1:
                raise InvalidPipe

            # Start a thread to wait for a client to connect
            threading.Thread(target=self._wait_for_client, args=(handle,), daemon=True).start()

            # Create reader and writer for the pipe
            return _SocketReader(handle), _SocketWriter(handle)
        except Exception as e:
            raise InvalidPipe from e

    def _wait_for_client(self, handle):
        ctypes.windll.kernel32.ConnectNamedPipe(handle, None)
        
    def handshake(self):
        ipc_path = get_ipc_path(self.pipe)
        if not ipc_path:
            raise DiscordNotFound

        self.create_reader_writer(ipc_path)

        self.send_data(0, {"v": 1, "client_id": self.client_id})
        preamble = self.sock_reader.read(8)
        if len(preamble) < 8:
            raise InvalidPipe
        code, length = struct.unpack("<ii", preamble)
        data = json.loads(self.sock_reader.read(length))
        if "code" in data:
            if data["message"] == "Invalid Client ID":
                raise InvalidID
            raise DiscordError(data["code"], data["message"])
        if self._events_on:
            # Allow user to override event handling by providing `on_event`
            self.sock_reader.feed_data = self.on_event


class _SocketReader:
    def __init__(self, sock):
        self._sock = sock

    def read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise BrokenPipeError()
            data += chunk
        return data


class _SocketWriter:
    def __init__(self, sock):
        self._sock = sock

    def write(self, data: bytes):
        total_sent = 0
        while total_sent < len(data):
            sent = self._sock.send(data[total_sent:])
            if sent == 0:
                raise BrokenPipeError()
            total_sent += sent

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass
