"""
Inspector tool — debug window capture and image matching.

Shows window info, live capture previews from each capture method,
and helps diagnose why image detection might be failing.
"""

import ctypes
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, filedialog

from gui import theme, widgets


def _print_window_capture(hwnd: int, flags: int) -> Optional[np.ndarray]:
    """Capture a window's client area with PrintWindow, as RGB uint8.

    The engine no longer captures this way (it uses WGC and falls back to a
    screen grab), but whether PrintWindow works on a given window is still worth
    knowing when WGC comes back blank — so the Inspector keeps testing it.
    ``flags=3`` includes PW_RENDERFULLCONTENT, which DirectX and Chromium-based
    windows need to render anything at all.
    """
    import win32gui
    import win32ui

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None

    window_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(window_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(src_dc, w, h)
    mem_dc.SelectObject(bitmap)
    try:
        if not ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), flags):
            return None
        info = bitmap.GetInfo()
        arr = np.frombuffer(bitmap.GetBitmapBits(True), dtype=np.uint8)
        arr = arr.reshape((info["bmHeight"], info["bmWidth"], 4))
        return arr[:, :, 2::-1].copy()          # BGRA -> RGB
    finally:
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.DeleteObject(bitmap.GetHandle())
        win32gui.ReleaseDC(hwnd, window_dc)


def _capture_methods_for_hwnd(hwnd: int) -> dict:
    """Try each capture method and return results dict.

    Returns:
        {
            "wgc": (image_or_None, error_msg),
            "printwindow_3": (image_or_None, error_msg),
            "printwindow_1": (image_or_None, error_msg),
            "screen_grab": (image_or_None, error_msg),
            "window_info": {...}
        }
    """
    import win32gui

    results = {
        "window_info": {
            "hwnd": hwnd,
            "title": "",
            "rect": None,
            "client_rect": None,
            "is_window": False,
            "is_iconic": False,
            "is_visible": False,
        },
        "wgc": (None, ""),
        "printwindow_3": (None, ""),
        "printwindow_1": (None, ""),
        "screen_grab": (None, ""),
    }

    # Get window info
    try:
        results["window_info"]["is_window"] = bool(win32gui.IsWindow(hwnd))
        results["window_info"]["is_iconic"] = bool(win32gui.IsIconic(hwnd))
        results["window_info"]["is_visible"] = bool(win32gui.IsWindowVisible(hwnd))
        results["window_info"]["title"] = win32gui.GetWindowText(hwnd)
        results["window_info"]["rect"] = win32gui.GetWindowRect(hwnd)
        results["window_info"]["client_rect"] = win32gui.GetClientRect(hwnd)
    except Exception as e:
        results["window_info"]["error"] = str(e)
        return results

    # Try WGC
    try:
        from engine import wgc_capture
        if wgc_capture.is_available():
            img = wgc_capture.get_frame(hwnd)
            if img is not None:
                std = float(np.std(img))
                results["wgc"] = (img, f"OK (std={std:.1f})")
            else:
                results["wgc"] = (None, "Failed to get frame")
        else:
            results["wgc"] = (None, "Not available")
    except Exception as e:
        results["wgc"] = (None, f"Error: {str(e)}")

    # Try PrintWindow
    for flags, name in [(3, "printwindow_3"), (1, "printwindow_1")]:
        try:
            arr = _print_window_capture(hwnd, flags)
            if arr is not None:
                std = float(np.std(arr))
                if std > 4.0:
                    rgb8 = np.clip(arr, 0, 255).astype(np.uint8)
                    results[name] = (rgb8, f"OK (std={std:.1f})")
                else:
                    results[name] = (None, f"All blank (std={std:.1f})")
            else:
                results[name] = (None, "Returned None")
        except Exception as e:                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         
            results[name] = (None, f"Error: {str(e)}")

    # Try screen grab
    try:
        from engine import image_matcher
        img = image_matcher._try_screen_grab_window_cv(hwnd)
        if img is not None:
            std = float(np.std(img))
            results["screen_grab"] = (img, f"OK (std={std:.1f})")
        else:
            results["screen_grab"] = (None, "Returned None")
    except Exception as e:
        results["screen_grab"] = (None, f"Error: {str(e)}")

    return results


class _WindowPickerDialog:
    """Simple listbox dialog to pick a window."""

    def __init__(self, parent, windows: list):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Pick a Window")
        self.top.geometry(f"{theme.px(400)}x{theme.px(400)}")

        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(frame, text="Select a window:").pack(anchor=tk.W)

        # Listbox with scrollbar
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 10))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # Populate with windows
        self.windows = windows
        for hwnd, title in windows:
            self.listbox.insert(tk.END, f"{title[:70]}")

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="OK", command=self._ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.LEFT)

        self.listbox.bind("<Double-Button-1>", lambda _: self._ok())

    def _ok(self):
        idx = self.listbox.curselection()
        if idx:
            self.result = self.windows[idx[0]]
        self.top.destroy()

    def _cancel(self):
        self.result = None
        self.top.destroy()


class InspectorWindow:
    """Debug window for capture inspection."""

    def __init__(self, parent):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title("Window Inspector")
        self.window.geometry(f"{theme.px(1200)}x{theme.px(700)}")
        self.window.configure(bg=theme.BG)

        self._current_hwnd = None
        self._capture_results = None
        self._auto_refresh = False

        self._build_ui()

    def _build_ui(self):
        """Build the inspector UI."""
        # Top frame: window picker
        top_frame = ttk.Frame(self.window)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        ttk.Label(top_frame, text="Window HWND:").pack(side=tk.LEFT)
        self._hwnd_entry = ttk.Entry(top_frame, width=15)
        self._hwnd_entry.pack(side=tk.LEFT, padx=5)

        ttk.Button(
            top_frame, text="Pick Window", command=self._pick_window
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            top_frame, text="Refresh", command=self._refresh
        ).pack(side=tk.LEFT, padx=5)

        self._auto_var = tk.BooleanVar()
        ttk.Checkbutton(
            top_frame, text="Auto-refresh (2s)", variable=self._auto_var,
            command=self._toggle_auto_refresh
        ).pack(side=tk.LEFT, padx=5)

        # Middle frame: window info + tabs for each capture method
        mid_frame = ttk.PanedWindow(self.window, orient=tk.HORIZONTAL)
        mid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left: window info
        left_frame = ttk.Frame(mid_frame)
        mid_frame.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Window Info", font=("Courier", 10, "bold")).pack(
            anchor=tk.W
        )
        self._info_text = widgets.ScrolledText(left_frame, height=20, width=40)
        self._info_text.pack(fill=tk.BOTH, expand=True)

        # Right: tabs for each capture method
        right_frame = ttk.Frame(mid_frame)
        mid_frame.add(right_frame, weight=2)

        self._notebook = ttk.Notebook(right_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._capture_tabs = {}
        for method in ["wgc", "printwindow_3", "printwindow_1", "screen_grab"]:
            frame = ttk.Frame(self._notebook)
            self._notebook.add(frame, text=method)

            # Status label
            status_frame = ttk.Frame(frame)
            status_frame.pack(fill=tk.X, padx=5, pady=5)
            status_label = ttk.Label(status_frame, text="", foreground="gray")
            status_label.pack(anchor=tk.W)

            # Canvas for preview
            canvas = tk.Canvas(frame, bg=theme.BG, cursor="cross")
            canvas.pack(fill=tk.BOTH, expand=True)

            self._capture_tabs[method] = {
                "frame": frame,
                "status": status_label,
                "canvas": canvas,
                "image": None,
                "photo": None,
            }

        self._build_templates_tab()

    def _build_templates_tab(self):
        """A tab that scores every captured template against this window.

        The answer to "why doesn't my template match?", which until now was only
        reachable from a CLI in `tools/` — invisible to anyone who had not read the
        source, though it is the diagnostic that found the discovery-ration bug, a
        wrong threshold and two duplicate templates in three days of live use.
        """
        frame = ttk.Frame(self._notebook)
        self._notebook.add(frame, text="templates")

        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bar, text="Score templates",
                   command=self._score_templates).pack(side=tk.LEFT)
        ttk.Label(bar, text="threshold").pack(side=tk.LEFT, padx=(12, 4))
        self._threshold_entry = ttk.Entry(bar, width=6)
        self._threshold_entry.insert(0, "0.80")
        self._threshold_entry.pack(side=tk.LEFT)
        self._templates_status = ttk.Label(bar, text="", foreground="gray")
        self._templates_status.pack(side=tk.LEFT, padx=12)

        self._templates_text = widgets.ScrolledText(frame, height=24, width=80)
        self._templates_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        self._templates_text.insert(
            tk.END,
            "Pick a window above, then Score templates.\n\n"
            "Scores are raw correlation. Measured on a live game window, a template "
            "whose element is on screen scores about 0.92 to 0.99, and absent ones "
            "reach about 0.47. If everything you own scores in the 0.40s, nothing is "
            "matching — check you picked the right window, and that it is not "
            "minimised.\n")

    def _score_templates(self):
        """Run the report off the UI thread; it takes seconds on a large pack."""
        try:
            hwnd = int(self._hwnd_entry.get())
        except ValueError:
            self._templates_status.configure(text="pick a window first")
            return
        try:
            threshold = float(self._threshold_entry.get())
        except ValueError:
            threshold = 0.80
            self._threshold_entry.delete(0, tk.END)
            self._threshold_entry.insert(0, "0.80")

        self._templates_status.configure(text="scoring…")
        self._templates_text.delete("1.0", tk.END)

        def work():
            from engine import match_report as mr
            try:
                report = mr.score_templates(hwnd, threshold=threshold)
            except mr.ReportError as exc:
                self._post(self._show_template_error, str(exc))
                return
            except Exception as exc:                      # pragma: no cover
                self._post(self._show_template_error, repr(exc))
                return
            self._post(self._show_template_report, report)

        threading.Thread(target=work, daemon=True, name="match-report").start()

    def _post(self, fn, *args):
        """Hand a result back to the UI thread, tolerating a window that has gone.

        Scoring takes seconds, and the user can close the Inspector while it runs —
        after which `after()` raises out of the worker and prints a traceback at them
        for having closed a window.
        """
        try:
            self.window.after(0, fn, *args)
        except (tk.TclError, RuntimeError):
            pass

    def _show_template_error(self, message: str):
        self._templates_status.configure(text="")
        self._templates_text.delete("1.0", tk.END)
        self._templates_text.insert(tk.END, message + "\n")

    def _show_template_report(self, report):
        from engine import match_report as mr

        lines = [
            f"{report.title}   captured {report.haystack[0]}x{report.haystack[1]}",
            f"threshold {report.threshold:.2f} "
            f"(effective {report.effective:.2f} when the frame came from WGC)",
            "",
            f"{'template':<38}{'std':>6}{'score':>8}   where",
            "-" * 72,
        ]
        for row in report.rows:
            std = f"{row.std:6.1f}" if row.std is not None else f"{'—':>6}"
            if row.matched:
                where = f"({row.at[0]},{row.at[1]})"
                lines.append(f"{row.name:<38}{std}{row.score:8.3f}   {where}")
            elif row.status == mr.NO_MATCH:
                lines.append(f"{row.name:<38}{std}{'-':>8}   not on this screen")
            else:
                lines.append(f"{row.name:<38}{std}{'—':>8}   "
                             f"{row.status.upper()}: {row.note}")

        lines += ["", report.summary + ".", "", mr.ADVICE, ""]
        self._templates_status.configure(
            text=f"{report.matched}/{len(report.rows)} matched")
        self._templates_text.delete("1.0", tk.END)
        self._templates_text.insert(tk.END, "\n".join(lines))

    def _pick_window(self):
        """Show list of open windows to pick from."""
        import win32gui

        def enum_windows(hwnd, windows):
            """Collect visible windows."""
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                title = win32gui.GetWindowText(hwnd)
                if title and len(title) > 1:  # Skip empty titles
                    windows.append((hwnd, title))
            except Exception:
                pass

        windows = []
        win32gui.EnumWindows(enum_windows, windows)

        # Sort by title
        windows.sort(key=lambda w: w[1].lower())

        if not windows:
            return

        # Show picker dialog
        from tkinter import simpledialog
        choices = [f"{title[:60]}" for _, title in windows]

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        dialog = _WindowPickerDialog(root, windows)
        root.wait_window(dialog.top)

        if dialog.result is not None:
            hwnd, title = dialog.result
            self._hwnd_entry.delete(0, tk.END)
            self._hwnd_entry.insert(0, str(hwnd))
            self._refresh()

        root.destroy()

    def _refresh(self):
        """Refresh all captures."""
        try:
            hwnd = int(self._hwnd_entry.get())
        except ValueError:
            self._info_text.delete("1.0", tk.END)
            self._info_text.insert(tk.END, "Invalid HWND")
            return

        self._current_hwnd = hwnd
        self._capture_results = _capture_methods_for_hwnd(hwnd)
        self._update_display()

    def _toggle_auto_refresh(self):
        """Toggle auto-refresh."""
        if self._auto_var.get():
            self._auto_refresh = True
            self._auto_refresh_loop()
        else:
            self._auto_refresh = False

    def _auto_refresh_loop(self):
        """Auto-refresh loop."""
        if self._auto_refresh:
            self._refresh()
            self.window.after(2000, self._auto_refresh_loop)

    def _update_display(self):
        """Update all displays with capture results."""
        if not self._capture_results:
            return

        info = self._capture_results["window_info"]
        self._info_text.delete("1.0", tk.END)
        text = f"""HWND: {info['hwnd']}
Title: {info['title']}
Valid: {info['is_window']}
Iconic (minimized): {info['is_iconic']}
Visible: {info['is_visible']}

Window Rect: {info['rect']}
Client Rect: {info['client_rect']}
"""
        if "error" in info:
            text += f"\nError: {info['error']}"
        self._info_text.insert(tk.END, text)

        # Update each tab
        for method in ["wgc", "printwindow_3", "printwindow_1", "screen_grab"]:
            img, status_msg = self._capture_results[method]
            tab_info = self._capture_tabs[method]

            # Update status
            color = "green" if img is not None else "red"
            tab_info["status"].configure(text=status_msg, foreground=color)

            # Draw image if available
            if img is not None:
                self._draw_preview(tab_info, img)
            else:
                tab_info["canvas"].delete("all")
                tab_info["canvas"].create_text(
                    10, 10, text=status_msg, fill="red", anchor=tk.NW
                )

    def _draw_preview(self, tab_info: dict, image: np.ndarray):
        """Draw image preview on canvas."""
        canvas = tab_info["canvas"]
        h, w = image.shape[:2]
        max_w, max_h = 400, 300

        # Scale if too large
        scale = min(1.0, max_w / w, max_h / h)
        new_w, new_h = int(w * scale), int(h * scale)

        if scale < 1.0:
            small_img = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            small_img = image

        # Convert BGR to RGB for PIL
        rgb = cv2.cvtColor(small_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(pil_img)

        # Store reference to prevent GC
        tab_info["photo"] = photo
        tab_info["image"] = image

        # Draw on canvas
        canvas.delete("all")
        canvas.create_image(5, 5, image=photo, anchor=tk.NW)
        canvas.create_text(
            5,
            small_img.shape[0] + 10,
            text=f"Size: {image.shape[1]}x{image.shape[0]}",
            fill="white",
            anchor=tk.NW,
        )
