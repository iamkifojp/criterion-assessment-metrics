"""Native Windows folder selection and known-folder helpers.

The picker runs out of process so its COM single-threaded apartment never
interacts with Streamlit's script thread.  This module intentionally has no
third-party or tkinter dependency; the portable CAM runtime does not ship Tcl.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import threading


def pick_folder(title: str, initial: str | None = None) -> str | None:
    """Open the native folder picker in a child process and return its result."""
    if os.name != "nt":
        return None
    command = [sys.executable, "-m", "engine.folder_dialog", "--title", title]
    if initial:
        command.extend(["--initial", initial])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    chosen = result.stdout.strip()
    return chosen or None


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "_GUID":
        import uuid
        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)


def _method(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(table[index])


def _bring_dialog_forward(stop: threading.Event) -> None:
    """Promote this process's dialog window while IFileDialog.Show blocks."""
    user32 = ctypes.windll.user32
    pid = os.getpid()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd)
        return True

    callback = callback_type(visit)
    while not stop.wait(0.08):
        user32.EnumWindows(callback, 0)


def _pick_folder_com(title: str, initial: str | None) -> str | None:
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    hr = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    if hr not in (0, 1):
        raise OSError(f"CoInitializeEx failed: 0x{hr & 0xffffffff:08x}")

    dialog = ctypes.c_void_p()
    clsid = _GUID.parse("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    iid = _GUID.parse("D57C7288-D4AD-4768-BE02-9D969532D960")
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 0x1, ctypes.byref(iid), ctypes.byref(dialog))
        if hr < 0:
            raise OSError(f"CoCreateInstance failed: 0x{hr & 0xffffffff:08x}")

        get_options = _method(dialog, 10, ctypes.c_long,
                              ctypes.POINTER(wintypes.DWORD))
        set_options = _method(dialog, 9, ctypes.c_long, wintypes.DWORD)
        options = wintypes.DWORD()
        get_options(dialog, ctypes.byref(options))
        set_options(dialog, options.value | 0x20 | 0x800)  # PICKFOLDERS | FORCEFILESYSTEM
        _method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)(dialog, title)

        if initial and os.path.isdir(initial):
            item = ctypes.c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                initial, None, ctypes.byref(_GUID.parse(
                    "43826D1E-E718-42EE-BC55-A1E261C37BFE")), ctypes.byref(item))
            if hr >= 0 and item:
                try:
                    _method(dialog, 12, ctypes.c_long, ctypes.c_void_p)(dialog, item)
                finally:
                    _method(item, 2, wintypes.ULONG)(item)

        stop = threading.Event()
        promoter = threading.Thread(target=_bring_dialog_forward, args=(stop,), daemon=True)
        promoter.start()
        try:
            hr = _method(dialog, 3, ctypes.c_long, wintypes.HWND)(dialog, None)
        finally:
            stop.set()
            promoter.join(timeout=0.3)
        if hr == -2147023673:  # HRESULT_FROM_WIN32(ERROR_CANCELLED)
            return None
        if hr < 0:
            raise OSError(f"IFileDialog.Show failed: 0x{hr & 0xffffffff:08x}")

        item = ctypes.c_void_p()
        hr = _method(dialog, 20, ctypes.c_long,
                     ctypes.POINTER(ctypes.c_void_p))(dialog, ctypes.byref(item))
        if hr < 0:
            return None
        try:
            path = ctypes.c_wchar_p()
            hr = _method(item, 5, ctypes.c_long, ctypes.c_int,
                         ctypes.POINTER(ctypes.c_wchar_p))(item, 0x80058000,
                                                         ctypes.byref(path))
            if hr < 0 or not path.value:
                return None
            chosen = path.value
            ole32.CoTaskMemFree(path)
            return chosen
        finally:
            _method(item, 2, wintypes.ULONG)(item)
    finally:
        if dialog:
            _method(dialog, 2, wintypes.ULONG)(dialog)
        ole32.CoUninitialize()


def _pick_folder_powershell(title: str, initial: str | None) -> str | None:
    # PowerShell is a last-resort UI fallback for Windows builds where COM
    # initialisation is unavailable. Arguments travel through environment
    # variables, avoiding shell interpolation of teacher-controlled paths.
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description=$env:CAM_PICK_TITLE; $d.ShowNewFolderButton=$true; "
        "if($env:CAM_PICK_INITIAL){$d.SelectedPath=$env:CAM_PICK_INITIAL}; "
        "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $d.SelectedPath}"
    )
    env = os.environ.copy()
    env["CAM_PICK_TITLE"] = title
    env["CAM_PICK_INITIAL"] = initial or ""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    chosen = result.stdout.strip()
    return chosen or None


def documents_folder() -> str:
    """Return Windows' redirected Documents folder, with safe fallbacks."""
    override = os.environ.get("CAM_DOCUMENTS_OVERRIDE", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if os.name != "nt":
        return os.path.join(os.path.expanduser("~"), "Documents")
    path = ctypes.c_wchar_p()
    folder_id = _GUID.parse("FDD39AD0-238F-46AF-ADB4-6C85480369C7")
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path))
        if hr >= 0 and path.value:
            return path.value
    except (AttributeError, OSError):
        pass
    finally:
        if path.value:
            ctypes.windll.ole32.CoTaskMemFree(path)
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                        "Documents")


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="Select a folder")
    parser.add_argument("--initial")
    args = parser.parse_args()
    try:
        chosen = _pick_folder_com(args.title, args.initial)
    except (AttributeError, OSError):
        chosen = _pick_folder_powershell(args.title, args.initial)
    if chosen:
        print(chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
