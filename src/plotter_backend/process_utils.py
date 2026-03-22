from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple


def run_cmd(
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout_s: Optional[float] = None,
    *,
    platform: str = sys.platform,
    subprocess_module=subprocess,
    threading_module=threading,
    ctypes_module=ctypes,
    time_module=time,
    inkscape_auto_accept_pdf_import_dialog: bool = True,
    inkscape_pdf_dialog_watcher_enabled: bool = False,
    inkscape_pdf_import_dialog_titles: Tuple[str, ...] = (),
    inkscape_pdf_import_dialog_timeout_s: float = 45.0,
) -> Tuple[int, str, str]:
    run_kwargs = {"shell": False}
    if platform.startswith("win") and hasattr(subprocess_module, "CREATE_NO_WINDOW"):
        run_kwargs["creationflags"] = subprocess_module.CREATE_NO_WINDOW

    def _is_inkscape_pdf_call(argv: List[str]) -> bool:
        if not argv:
            return False
        exe = Path(str(argv[0])).name.lower()
        if "inkscape" not in exe:
            return False
        return any(str(part).lower().endswith(".pdf") for part in argv[1:])

    def _auto_accept_inkscape_pdf_import_dialog(proc) -> None:
        if not platform.startswith("win"):
            return
        if not inkscape_auto_accept_pdf_import_dialog:
            return
        if not proc or proc.poll() is not None:
            return

        user32 = ctypes_module.windll.user32  # type: ignore[attr-defined]
        WM_COMMAND = 0x0111
        IDOK = 1
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        VK_RETURN = 0x0D
        BM_CLICK = 0x00F5

        enum_windows = user32.EnumWindows
        is_window_visible = user32.IsWindowVisible
        get_window_text_length = user32.GetWindowTextLengthW
        get_window_text = user32.GetWindowTextW
        get_window_thread_process_id = user32.GetWindowThreadProcessId
        post_message = user32.PostMessageW
        enum_child_windows = user32.EnumChildWindows
        send_message = user32.SendMessageW
        set_foreground_window = user32.SetForegroundWindow

        title_tokens = tuple(token.lower() for token in inkscape_pdf_import_dialog_titles if token)
        deadline = time_module.time() + max(2.0, float(inkscape_pdf_import_dialog_timeout_s))

        def _window_title(hwnd: int) -> str:
            if not is_window_visible(hwnd):
                return ""
            length = int(get_window_text_length(hwnd))
            if length <= 0:
                return ""
            buf = ctypes_module.create_unicode_buffer(length + 1)
            get_window_text(hwnd, buf, length + 1)
            return str(buf.value or "")

        while proc.poll() is None and time_module.time() < deadline:
            found_hwnd = 0

            @ctypes_module.WINFUNCTYPE(ctypes_module.c_bool, ctypes_module.c_void_p, ctypes_module.c_void_p)
            def _enum_cb(hwnd, _lparam):
                nonlocal found_hwnd
                if found_hwnd:
                    return False
                title = _window_title(hwnd)
                if not title:
                    return True
                low = title.lower()
                if not any(token in low for token in title_tokens):
                    return True
                pid = ctypes_module.c_ulong(0)
                get_window_thread_process_id(hwnd, ctypes_module.byref(pid))
                if int(pid.value) != int(proc.pid):
                    return True
                found_hwnd = int(hwnd)
                return False

            try:
                enum_windows(_enum_cb, 0)
            except Exception:
                time_module.sleep(0.15)
                continue

            if found_hwnd:
                try:
                    set_foreground_window(found_hwnd)
                except Exception:
                    pass
                try:
                    post_message(found_hwnd, WM_COMMAND, IDOK, 0)
                except Exception:
                    pass

                clicked = {"ok": False}

                @ctypes_module.WINFUNCTYPE(ctypes_module.c_bool, ctypes_module.c_void_p, ctypes_module.c_void_p)
                def _child_cb(child, _lparam):
                    if clicked["ok"]:
                        return False
                    tlen = int(get_window_text_length(child))
                    if tlen <= 0:
                        return True
                    tbuf = ctypes_module.create_unicode_buffer(tlen + 1)
                    get_window_text(child, tbuf, tlen + 1)
                    txt = str(tbuf.value or "").strip().lower()
                    if txt in {"ok", "ок"}:
                        try:
                            send_message(child, BM_CLICK, 0, 0)
                            clicked["ok"] = True
                            return False
                        except Exception:
                            return True
                    return True

                try:
                    enum_child_windows(found_hwnd, _child_cb, 0)
                except Exception:
                    pass
                try:
                    post_message(found_hwnd, WM_KEYDOWN, VK_RETURN, 0)
                    post_message(found_hwnd, WM_KEYUP, VK_RETURN, 0)
                except Exception:
                    pass
            time_module.sleep(0.15)

    if _is_inkscape_pdf_call(cmd) and inkscape_pdf_dialog_watcher_enabled:
        proc = subprocess_module.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess_module.PIPE,
            stderr=subprocess_module.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **run_kwargs,
        )
        watcher = threading_module.Thread(
            target=_auto_accept_inkscape_pdf_import_dialog,
            args=(proc,),
            daemon=True,
        )
        watcher.start()
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess_module.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            out, err = proc.communicate()
            raise
        return int(proc.returncode or 0), out, err

    result = subprocess_module.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        **run_kwargs,
    )
    return result.returncode, result.stdout, result.stderr


def open_with_default_viewer(
    path: Path,
    *,
    logger=print,
    startfile: Optional[Callable[[str], None]] = getattr(os, "startfile", None),
    format_internal_exception: Callable[[str, Exception], str],
) -> None:
    try:
        if startfile is None:
            raise OSError("os.startfile is unavailable")
        startfile(str(path))
        logger(f"Opened preview: {path}")
    except Exception as exc:
        logger(format_internal_exception("Cannot open preview automatically", exc))
