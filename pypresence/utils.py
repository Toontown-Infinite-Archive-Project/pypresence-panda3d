"""Util functions that are needed but messy.

This project removes asyncio usage; helpers here avoid importing asyncio so
the library can be driven by Panda3D tasks or other event systems.
"""
import os
import socket
import sys
import tempfile


def remove_none(d: dict):
    for item in d.copy():
        if isinstance(d[item], dict):
            if len(d[item]):
                d[item] = remove_none(d[item])
            if not len(d[item]):
                del d[item]
        elif d[item] is None:
            del d[item]
    return d


def test_ipc_path(path) -> bool:
    """Tests an IPC pipe to ensure that it actually works"""
    if sys.platform == "win32":
        with open(path):
            return True
    else:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            return True


# Returns on first IPC pipe matching Discord's
def get_ipc_path(pipe=None):
    ipc = "discord-ipc-"
    if pipe is not None:
        ipc = f"{ipc}{pipe}"

    if sys.platform in ("linux", "darwin"):
        tempdir = os.environ.get("XDG_RUNTIME_DIR") or (
            f"/run/user/{os.getuid()}"
            if os.path.exists(f"/run/user/{os.getuid()}")
            else tempfile.gettempdir()
        )
        paths = [
            ".",
            "..",
            "snap.discord",
            "app/com.discordapp.Discord",
            "app/com.discordapp.DiscordCanary",
        ]
    elif sys.platform == "win32":
        tempdir = r"\\?\pipe"
        paths = ["."]
    else:
        return

    for path in paths:
        full_path = os.path.abspath(os.path.join(tempdir, path))
        if sys.platform == "win32" or os.path.isdir(full_path):
            for entry in os.scandir(full_path):
                if (
                    entry.name.startswith(ipc)
                    and os.path.exists(entry)
                    and test_ipc_path(entry.path)
                ):
                    return entry.path


def get_event_loop(force_fresh: bool = False):
    # Asyncio has been removed from the core library for Panda3D compatibility.
    # Return None as a placeholder; callers should not rely on an asyncio loop.
    return None
