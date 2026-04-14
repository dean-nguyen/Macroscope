"""
Inspector tool — debug window capture and image matching.

Shows window info, live capture previews from each capture method,
and helps diagnose why image detection might be failing.
"""

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
    from engine import image_matcher
    for flags, name in [(3, "printwindow_3"), (1, "printwindow_1")]:
        try:
            arr = image_matcher._try_print_window(hwnd, flags=flags)
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
        self.top.geometry("400x400")

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
        self.window.geometry("1200x700")
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
