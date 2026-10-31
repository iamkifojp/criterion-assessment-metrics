"""Native "choose a folder" / "choose a PDF" dialogs for Windows and macOS.

A browser cannot tell the server where a folder is on disk, so the server opens
the system dialog itself.

* **Windows** — the modern IFileOpenDialog through ctypes (ported from CAM's
  ``engine/folder_dialog.py``), run in a child process so its COM apartment
  never touches Flask's threads. PowerShell's dialog is the fallback.
* **macOS** — AppleScript ``choose folder`` / ``choose file`` via
  ``osascript``. Text is passed as arguments, never pasted into the script.

Each picker returns the chosen path, or None if the teacher cancelled.
Small files (class lists, rubrics) are uploaded through the browser instead.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("folder", "pdf")


def pick_folder(title: str, initial: str | None = None) -> str | None:
    return _pick("folder", title, initial)


def pick_pdf(title: str, initial: str | None = None) -> str | None:
    return _pick("pdf", title, initial)


def _pick(mode: str, title: str, initial: str | None) -> str | None:
    if os.name == "nt":
        return _pick_windows_child(mode, title, initial)
    if sys.platform == "darwin":
        return _pick_macos(mode, title, initial)
    return None


# --- macOS --------------------------------------------------------------------------

_MAC_SCRIPTS = {
    "folder": (
        'on run argv\n'
        '  activate\n'
        '  if (count of argv) > 1 then\n'
        '    set chosen to choose folder with prompt (item 1 of argv) '
        'default location (POSIX file (item 2 of argv))\n'
        '  else\n'
        '    set chosen to choose folder with prompt (item 1 of argv)\n'
        '  end if\n'
        '  return POSIX path of chosen\n'
        'end run\n'),
    "pdf": (
        'on run argv\n'
        '  activate\n'
        '  if (count of argv) > 1 then\n'
        '    set chosen to choose file with prompt (item 1 of argv) '
        'of type {"com.adobe.pdf"} default location (POSIX file (item 2 of argv))\n'
        '  else\n'
        '    set chosen to choose file with prompt (item 1 of argv) of type {"com.adobe.pdf"}\n'
        '  end if\n'
        '  return POSIX path of chosen\n'
        'end run\n'),
}


def _pick_macos(mode: str, title: str, initial: str | None) -> str | None:
    command = ["osascript", "-e", _MAC_SCRIPTS[mode], title]
    if initial and os.path.isdir(initial):
        command.append(initial)
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=False)
    except OSError:
        return None
    if result.returncode != 0:          # includes "User canceled" (-128)
        return None
    chosen = result.stdout.strip()
    if len(chosen) > 1:
        chosen = chosen.rstrip("/")
    return chosen or None


# --- Windows ------------------------------------------------------------------------

def _pick_windows_child(mode: str, title: str, initial: str | None) -> str | None:
    command = [sys.executable, "-m", "engine.pickers", "--mode", mode, "--title", title]
    if initial:
        command.extend(["--initial", initial])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, cwd=APP_ROOT,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


if os.name == "nt":
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        @classmethod
        def parse(cls, value: str) -> "_GUID":
            import uuid
            return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    class _FilterSpec(ctypes.Structure):
        _fields_ = [("pszName", wintypes.LPCWSTR), ("pszSpec", wintypes.LPCWSTR)]

    def _method(obj, index, restype, *argtypes):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])

    def _bring_dialog_forward(stop: threading.Event) -> None:
        """Keep this process's dialog on top while IFileDialog.Show blocks."""
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

    # IFileDialog vtable slots
    _SHOW, _SET_FILE_TYPES, _SET_OPTIONS, _GET_OPTIONS = 3, 4, 9, 10
    _SET_FOLDER, _SET_TITLE, _GET_RESULT, _RELEASE = 12, 17, 20, 2
    _FOS_PICKFOLDERS, _FOS_FORCEFILESYSTEM = 0x20, 0x40
    _FOS_PATHMUSTEXIST, _FOS_FILEMUSTEXIST = 0x800, 0x1000

    def _pick_com(mode: str, title: str, initial: str | None) -> str | None:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        hr = ole32.CoInitializeEx(None, 0x2)        # COINIT_APARTMENTTHREADED
        if hr not in (0, 1):
            raise OSError(f"CoInitializeEx failed: 0x{hr & 0xffffffff:08x}")
        dialog = ctypes.c_void_p()
        clsid = _GUID.parse("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")   # FileOpenDialog
        iid = _GUID.parse("D57C7288-D4AD-4768-BE02-9D969532D960")     # IFileOpenDialog
        try:
            hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 0x1,
                                        ctypes.byref(iid), ctypes.byref(dialog))
            if hr < 0:
                raise OSError(f"CoCreateInstance failed: 0x{hr & 0xffffffff:08x}")
            options = wintypes.DWORD()
            _method(dialog, _GET_OPTIONS, ctypes.c_long,
                    ctypes.POINTER(wintypes.DWORD))(dialog, ctypes.byref(options))
            wanted = options.value | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
            wanted |= _FOS_PICKFOLDERS if mode == "folder" else _FOS_FILEMUSTEXIST
            _method(dialog, _SET_OPTIONS, ctypes.c_long, wintypes.DWORD)(dialog, wanted)
            if mode == "pdf":
                specs = (_FilterSpec * 1)(_FilterSpec("PDF", "*.pdf"))
                _method(dialog, _SET_FILE_TYPES, ctypes.c_long, wintypes.UINT,
                        ctypes.POINTER(_FilterSpec))(dialog, 1, specs)
            _method(dialog, _SET_TITLE, ctypes.c_long, wintypes.LPCWSTR)(dialog, title)

            if initial and os.path.isdir(initial):
                item = ctypes.c_void_p()
                hr = shell32.SHCreateItemFromParsingName(
                    initial, None,
                    ctypes.byref(_GUID.parse("43826D1E-E718-42EE-BC55-A1E261C37BFE")),
                    ctypes.byref(item))
                if hr >= 0 and item:
                    try:
                        _method(dialog, _SET_FOLDER, ctypes.c_long, ctypes.c_void_p)(dialog, item)
                    finally:
                        _method(item, _RELEASE, wintypes.ULONG)(item)

            stop = threading.Event()
            promoter = threading.Thread(target=_bring_dialog_forward, args=(stop,),
                                        daemon=True)
            promoter.start()
            try:
                hr = _method(dialog, _SHOW, ctypes.c_long, wintypes.HWND)(dialog, None)
            finally:
                stop.set()
                promoter.join(timeout=0.3)
            if hr == -2147023673:                   # ERROR_CANCELLED
                return None
            if hr < 0:
                raise OSError(f"IFileDialog.Show failed: 0x{hr & 0xffffffff:08x}")

            item = ctypes.c_void_p()
            hr = _method(dialog, _GET_RESULT, ctypes.c_long,
                         ctypes.POINTER(ctypes.c_void_p))(dialog, ctypes.byref(item))
            if hr < 0:
                return None
            try:
                path = ctypes.c_wchar_p()
                hr = _method(item, 5, ctypes.c_long, ctypes.c_int,       # GetDisplayName
                             ctypes.POINTER(ctypes.c_wchar_p))(
                    item, 0x80058000, ctypes.byref(path))                # SIGDN_FILESYSPATH
                if hr < 0 or not path.value:
                    return None
                chosen = path.value
                ole32.CoTaskMemFree(path)
                return chosen
            finally:
                _method(item, _RELEASE, wintypes.ULONG)(item)
        finally:
            if dialog:
                _method(dialog, _RELEASE, wintypes.ULONG)(dialog)
            ole32.CoUninitialize()


def _pick_powershell(mode: str, title: str, initial: str | None) -> str | None:
    """Last-resort Windows dialog. Text travels in environment variables."""
    if mode == "folder":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description=$env:CAM2_PICK_TITLE; $d.ShowNewFolderButton=$true; "
            "if($env:CAM2_PICK_INITIAL){$d.SelectedPath=$env:CAM2_PICK_INITIAL}; "
            "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $d.SelectedPath}")
    else:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title=$env:CAM2_PICK_TITLE; $d.Filter='PDF (*.pdf)|*.pdf'; "
            "if($env:CAM2_PICK_INITIAL){$d.InitialDirectory=$env:CAM2_PICK_INITIAL}; "
            "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $d.FileName}")
    env = os.environ.copy()
    env["CAM2_PICK_TITLE"] = title
    env["CAM2_PICK_INITIAL"] = initial or ""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return None
    return result.stdout.strip() or None


def open_in_file_manager(folder: str) -> bool:
    """Show a folder in Explorer (Windows) or Finder (Mac). False if not possible."""
    if not os.path.isdir(folder):
        return False
    try:
        if os.name == "nt":
            os.startfile(folder)                      # noqa: S606 — a folder, not a program
            return True
        if sys.platform == "darwin":
            return subprocess.run(["open", folder], check=False).returncode == 0
    except OSError:
        return False
    return False


# --- Known folders ---------------------------------------------------------------------

def documents_folder() -> str:
    """The teacher's Documents folder (Windows may redirect it, e.g. to OneDrive)."""
    override = os.environ.get("CAM2_DOCUMENTS_OVERRIDE", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if os.name == "nt":
        path = ctypes.c_wchar_p()
        folder_id = _GUID.parse("FDD39AD0-238F-46AF-ADB4-6C85480369C7")   # FOLDERID_Documents
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
    return os.path.join(os.path.expanduser("~"), "Documents")


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES, default="folder")
    parser.add_argument("--title", default="Select")
    parser.add_argument("--initial")
    args = parser.parse_args()
    try:
        chosen = _pick_com(args.mode, args.title, args.initial)
    except (AttributeError, NameError, OSError):
        chosen = _pick_powershell(args.mode, args.title, args.initial)
    if chosen:
        sys.stdout.write(chosen + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
