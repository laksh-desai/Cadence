"""Windows DPAPI protection for small secrets kept on this computer (encryption keys, tokens).

DPAPI (CryptProtectData) encrypts with a key derived from the signed-in Windows user's login, so a
protected file is unreadable when copied to another machine or opened by another Windows account —
the secret is bound to this user on this computer. No extra dependency: it is called through ctypes.

Used for the intake (mailbox app password) encryption key. On a non-Windows machine (development
only) it falls back to returning the bytes unchanged, and `is_protected` says so.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_MAGIC = b"DPAPI1:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    """A DATA_BLOB over a buffer that lives as long as the blob. (Returning only a pointer into a
    temporary buffer let Python free it before Windows read it — intermittent "CryptUnprotectData
    failed", found by the test suite.)"""
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob._keep = buf
    return blob


def available() -> bool:
    return sys.platform == "win32"


def protect(data: bytes) -> bytes:
    if not available():
        return data
    out = _Blob()
    entropy = _blob(b"Cadence")
    src = _blob(data)
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "Cadence", ctypes.byref(entropy),
                                                  None, None, 0x01, ctypes.byref(out)):  # UI_FORBIDDEN
        raise OSError("CryptProtectData failed")
    try:
        return _MAGIC + ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(data: bytes) -> bytes:
    if not data.startswith(_MAGIC):
        return data                         # an older, unprotected value: still readable
    if not available():
        raise OSError("this secret was protected by Windows on another computer")
    raw = data[len(_MAGIC):]
    out = _Blob()
    entropy = _blob(b"Cadence")
    src = _blob(raw)
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(entropy),
                                                    None, None, 0x01, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed — the secret belongs to another Windows user or PC")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def is_protected(data: bytes) -> bool:
    return data.startswith(_MAGIC)
