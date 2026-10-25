# Third-party notices

Oído's **source code** is released under the **MIT** license (see `LICENSE`).
The **installer and portable ZIP** also ship the components below, each under its own license.

| Component | Used for | License | Source |
|---|---|---|---|
| **FFmpeg / ffprobe** (BtbN static build) | Decoding, converting and measuring audio/video | **GPL v3** (`win64-gpl` build) | https://ffmpeg.org · https://github.com/BtbN/FFmpeg-Builds |
| **Qt 6 / PySide6 / shiboken6** | User interface | **LGPL v3** | https://www.qt.io · https://code.qt.io/cgit/pyside/pyside-setup.git |
| **Python** | Interpreter | PSF License | https://www.python.org |
| **Inter** (typeface) | User interface | SIL Open Font License 1.1 | https://github.com/rsms/inter |
| **NumPy** | Numerical analysis | BSD-3-Clause (plus permissive licenses of bundled parts) | https://numpy.org |

## Notes

- **FFmpeg** ships as a **separate program** (`_internal/bin/ffmpeg.exe`, `ffprobe.exe`) that Oído runs as an external process. Its license is in `_internal/bin/FFmpeg-LICENSE.txt` and the exact build origin in `_internal/bin/FFmpeg-SOURCE.txt`. FFmpeg's source code is at https://ffmpeg.org/download.html and the build scripts at https://github.com/BtbN/FFmpeg-Builds.
- **Qt / PySide6** ships as separate dynamic libraries (`.dll` files inside `_internal/`) that can be replaced with other compatible versions, as the LGPL v3 allows.
- If you need the corresponding source code of any of these components and the links above no longer work, open an issue in this repository.
