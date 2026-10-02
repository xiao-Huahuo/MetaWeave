"""Encrypt connection credentials at rest; the deployment key is DPAPI-protected on Windows."""
import ctypes
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet


def _windows_protect(data: bytes, decrypt: bool = False) -> bytes:
    """Protect the machine key for the current Windows identity; free native buffers."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        """Windows DATA_BLOB holding owned input or system-allocated output."""
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(target.data)


class ConnectionSecrets:
    """Application-owned credential cipher; key files contain no business records."""

    def __init__(self, config) -> None:
        """Create/read a private deployment key atomically, never regenerate an existing key."""
        path = Path(config.storage.base_data_dir) / config.mcp.secret_key_file
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        protected = _windows_protect(key) if os.name == "nt" else key
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            protected = path.read_bytes()
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(protected)
        self.cipher = Fernet(_windows_protect(protected, True) if os.name == "nt" else protected)

    def encrypt(self, values: dict) -> str:
        """Encode env/header values as authenticated ciphertext."""
        return self.cipher.encrypt(json.dumps(values, ensure_ascii=False).encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> dict:
        """Decode stored credentials; corruption fails without leaking the ciphertext."""
        return json.loads(self.cipher.decrypt(value.encode("ascii"))) if value else {}
