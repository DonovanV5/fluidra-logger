from __future__ import annotations


def format_window_geometry(width, height, x, y) -> str:
    return f"{int(width)}x{int(height)}{int(x):+d}{int(y):+d}"


def tk_attribute_enabled(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def current_monitor_geometry(window) -> tuple[int, int, int, int]:
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        monitor = ctypes.windll.user32.MonitorFromWindow(window.winfo_id(), 2)
        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            rect = monitor_info.rcMonitor
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 0 and height > 0:
                return rect.left, rect.top, width, height
    except Exception:
        pass

    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def present_app_dialog(parent, dialog, focus_widget=None, modal=True) -> None:
    """Keep app dialogs above the kiosk dashboard and ready for input."""
    def bring_forward():
        try:
            dialog.attributes("-topmost", True)
        except Exception:
            pass
        try:
            dialog.lift()
            dialog.focus_force()
        except Exception:
            pass
        if focus_widget is not None:
            try:
                focus_widget.focus_force()
            except Exception:
                try:
                    focus_widget.focus_set()
                except Exception:
                    pass

    try:
        dialog.transient(parent)
    except Exception:
        pass
    try:
        dialog.attributes("-topmost", True)
    except Exception:
        pass
    if modal:
        try:
            dialog.grab_set()
        except Exception:
            pass
    bring_forward()
    try:
        dialog.after(50, bring_forward)
        dialog.after(250, bring_forward)
    except Exception:
        pass


def scaled_font(size, scale, compact=False, weight=None):
    scale = float(scale or 1.0)
    if compact:
        scale = min(scale, 0.82)
    font_size = max(8, int(size * scale))
    return ("Arial", font_size, weight) if weight else ("Arial", font_size)


def scaled_dim(value, scale, minimum=1) -> int:
    return max(minimum, int(value * float(scale or 1.0)))


def set_textbox_value(textbox, value) -> None:
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")
    textbox.insert("1.0", value)
    textbox.configure(state="disabled")


def set_label_color(label, color) -> None:
    try:
        label.configure(text_color=color)
    except Exception:
        pass
