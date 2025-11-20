from __future__ import annotations

import os
import ctypes
import ctypes.wintypes
import time
import sys
import threading
from queue import Queue, Empty

class NamedPipe:
    def __init__(self, pipe_name: str):
        self.pipe_name = r'\\.\pipe\{}'.format(pipe_name)
        self.handle = None

    def create_pipe(self):
        self.handle = ctypes.windll.kernel32.CreateNamedPipeW(
            self.pipe_name,
            0x00000003,  # PIPE_ACCESS_DUPLEX
            0x00000000,  # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT
            1,           # Number of instances
            512,         # Output buffer size
            512,         # Input buffer size
            0,           # Client time-out
            None         # Default security attributes
        )
        if self.handle == ctypes.wintypes.INVALID_HANDLE_VALUE:
            raise Exception("Failed to create named pipe")

    def connect_pipe(self):
        connected_handle = ctypes.windll.kernel32.ConnectNamedPipe(self.handle, None)
        if not connected_handle:
            raise Exception("Failed to connect to named pipe")

    def read(self, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.wintypes.DWORD()
        success = ctypes.windll.kernel32.ReadFile(
            self.handle,
            buffer,
            size,
            ctypes.byref(bytes_read),
            None
        )
        if not success:
            raise Exception("Failed to read from named pipe")
        return buffer.raw[:bytes_read.value]

    def write(self, data: bytes):
        bytes_written = ctypes.wintypes.DWORD()
        success = ctypes.windll.kernel32.WriteFile(
            self.handle,
            data,
            len(data),
            ctypes.byref(bytes_written),
            None
        )
        if not success:
            raise Exception("Failed to write to named pipe")

    def close(self):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

def create_named_pipe(pipe_name: str) -> NamedPipe:
    # On Windows, create a real named pipe. On other platforms, create an
    # in-memory simulation so tests and non-Windows environments can run.
    if sys.platform == "win32":
        pipe = NamedPipe(pipe_name)
        pipe.create_pipe()
        return pipe
    else:
        # Use the provided full name as the key so callers passing
        # r"\\.\pipe\name" will match later lookups.
        _pipes_registry.setdefault(pipe_name, Queue())
        return pipe_name

def wait_for_client(pipe: NamedPipe):
    while True:
        try:
            pipe.connect_pipe()
            break
        except Exception:
            time.sleep(1)  # Wait before retrying

def cleanup_pipe(pipe: NamedPipe):
    pipe.close()


# --- Cross-platform helpers (in-memory simulation on non-Windows) ---
_pipes_registry: dict = {}
_pipes_lock = threading.Lock()


def named_pipe_exists(pipe_name: str) -> bool:
    """Return True if a named pipe with the given name exists (created).

    On Windows this will attempt to open the pipe; on other platforms it
    checks the in-memory registry created by `create_named_pipe`.
    """
    if sys.platform == "win32":
        # Try to open the pipe for reading to check existence
        GENERIC_READ = 0x80000000
        OPEN_EXISTING = 3
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        handle = CreateFileW(
            pipe_name,
            GENERIC_READ,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == ctypes.wintypes.HANDLE(-1).value:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    else:
        with _pipes_lock:
            return pipe_name in _pipes_registry


def send_message(pipe_name: str, data: bytes, timeout: float = 1.0) -> None:
    """Send a message to the named pipe (or simulated pipe).

    On non-Windows platforms this puts bytes into the in-memory queue.
    """
    if sys.platform == "win32":
        # Open the pipe and write
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        handle = CreateFileW(
            pipe_name,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == ctypes.wintypes.HANDLE(-1).value:
            raise FileNotFoundError("Named pipe not found: %s" % pipe_name)
        bytes_written = ctypes.wintypes.DWORD()
        success = ctypes.windll.kernel32.WriteFile(
            handle, data, len(data), ctypes.byref(bytes_written), None
        )
        ctypes.windll.kernel32.CloseHandle(handle)
        if not success:
            raise IOError("Failed to write to named pipe")
    else:
        with _pipes_lock:
            q = _pipes_registry.get(pipe_name)
            if q is None:
                raise FileNotFoundError("Named pipe not found: %s" % pipe_name)
            q.put(data, block=True, timeout=timeout)


def receive_message(pipe_name: str, timeout: float = 1.0) -> bytes:
    """Receive a message from the named pipe (or simulated pipe).

    On non-Windows platforms this reads bytes from the in-memory queue.
    """
    if sys.platform == "win32":
        # Open the pipe and read
        GENERIC_READ = 0x80000000
        OPEN_EXISTING = 3
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        handle = CreateFileW(
            pipe_name,
            GENERIC_READ,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == ctypes.wintypes.HANDLE(-1).value:
            raise FileNotFoundError("Named pipe not found: %s" % pipe_name)
        buffer = ctypes.create_string_buffer(4096)
        bytes_read = ctypes.wintypes.DWORD()
        success = ctypes.windll.kernel32.ReadFile(
            handle, buffer, ctypes.sizeof(buffer), ctypes.byref(bytes_read), None
        )
        ctypes.windll.kernel32.CloseHandle(handle)
        if not success:
            raise IOError("Failed to read from named pipe")
        return buffer.raw[: bytes_read.value]
    else:
        with _pipes_lock:
            q = _pipes_registry.get(pipe_name)
            if q is None:
                raise FileNotFoundError("Named pipe not found: %s" % pipe_name)
        try:
            return q.get(block=True, timeout=timeout)
        except Empty:
            raise TimeoutError("Timed out waiting for message on %s" % pipe_name)