# Window Macro Bot

A desktop automation tool for Windows that records and plays back mouse/keyboard macros with pixel detection, image matching, and background-window input.

## Features

- **Mouse & keyboard automation** — click, drag, scroll, type, hotkey combos
- **Pixel detection** — wait for or branch on pixel color at a coordinate
- **Image matching** — find UI elements by template screenshot (OpenCV)
- **Rectangle detection** — detect cards/buttons by contour analysis
- **Background mode** — send input via Win32 PostMessage without moving your real cursor
- **Window capture** — Windows.Graphics.Capture for GPU-accelerated screenshots
- **Global hotkeys** — trigger macros from anywhere with configurable key combos
- **Loop mode** — repeat macros continuously with configurable delay
- **Branching logic** — conditional action lists based on pixel/image match results
- **Folder organization** — group macros into folders, run all macros in a folder

## Requirements

- Windows 10/11
- Python 3.10+

## Setup

```bash
pip install -r requirements.txt
python main.py
```

## Macro format

Macros are JSON files in the `macros/` directory. See [`macros/SCHEMA.md`](macros/SCHEMA.md) for the full schema reference.

### Supported action types

| Action | Description |
|--------|-------------|
| `move` | Move cursor to coordinates |
| `click` | Click (left/right/middle, single or multi) |
| `double_click` | Double-click |
| `right_click` | Right-click |
| `drag` | Click-and-drag between two points |
| `scroll` | Scroll the mouse wheel |
| `key` | Press a key or key combo |
| `type` | Type a string character by character |
| `wait` | Pause execution |
| `pixel_wait` | Block until a pixel matches a color |
| `pixel_check` | Branch on pixel color |
| `find_and_click` | Find a template image and click it |
| `image_wait` | Block until a template image appears |
| `image_check` | Branch on template image visibility |
| `find_all_and_click` | Find all matches of a template and click each |
| `find_rects_and_click` | Detect rectangles by contour and click |

## Dependencies

| Package | Purpose |
|---------|---------|
| pyautogui | Mouse/keyboard automation (foreground) |
| keyboard | Global hotkey listener |
| Pillow | Screenshot capture, image processing |
| opencv-python | Template matching, contour detection |
| numpy | Array operations for image processing |
| pywin32 | Win32 API (PostMessage, window management) |
| windows-capture | Windows.Graphics.Capture bindings |
| pynput | Input monitoring |

## License

See [LICENSE](LICENSE).
