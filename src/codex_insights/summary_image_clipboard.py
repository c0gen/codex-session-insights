"""Native-only PNG operations; no indexing, HTTP payloads or account data."""
import base64
import binascii
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import re
import struct
import tempfile
import threading
import time
import zlib

MAX_PNG_BYTES = 2 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_ACTIONS = {"copy_summary_image", "save_summary_image", "summary_image_preferences"}


def png_payload(args):
    value = args.get("png_base64") if isinstance(args, dict) else None
    if not isinstance(value, str) or len(value) > 4 * ((MAX_PNG_BYTES + 2) // 3):
        raise ValueError("Summary image must be a PNG under 2 MiB")
    try:
        png = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid summary PNG") from None
    if len(png) > MAX_PNG_BYTES:
        raise ValueError("Summary image must be a PNG under 2 MiB")
    if not png.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid summary PNG")
    offset, chunks, ended = 8, [], False
    while offset + 12 <= len(png):
        size = struct.unpack_from(">I", png, offset)[0]
        end = offset + 12 + size
        if end > len(png):
            break
        kind, content = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + size]
        if zlib.crc32(kind + content) & 0xffffffff != struct.unpack_from(">I", png, end - 4)[0]:
            break
        if not chunks:
            if kind != b"IHDR" or size != 13 or struct.unpack_from(">II", content) != (1200, 720):
                break
        elif kind == b"IHDR":
            break
        chunks.append(kind)
        offset = end
        if kind == b"IEND":
            ended = size == 0 and offset == len(png)
            break
    if not ended or b"IDAT" not in chunks:
        raise ValueError("Invalid 1200 × 720 summary PNG")
    return png


class ClipboardBusy(Exception):
    pass


def copy_to_clipboard(adapter, png, stopped, pause=time.sleep):
    """Keep resources alive through the persistent write and bounded busy retries."""
    if stopped():
        raise RuntimeError("The app is closing")
    with adapter.prepare(png) as packet:
        for attempt in range(5):
            if stopped():
                raise RuntimeError("The app is closing")
            try:
                adapter.write(packet)
                return
            except ClipboardBusy:
                if attempt == 4:
                    raise RuntimeError("The clipboard is busy. Please try again") from None
                pause(.05)


class WindowsClipboard:
    @contextmanager
    def prepare(self, png):
        # Imported after pywebview initializes the Windows .NET runtime.
        from System import Array, Byte
        from System.IO import MemoryStream
        from System.Drawing import Image, Bitmap
        from System.Windows.Forms import DataObject, DataFormats
        with ExitStack() as stack:
            stream = MemoryStream(Array[Byte](png))
            stack.callback(stream.Dispose)
            image = Image.FromStream(stream, True, True)
            stack.callback(image.Dispose)
            bitmap = Bitmap(image)
            stack.callback(bitmap.Dispose)
            packet = DataObject()
            packet.SetData(DataFormats.Bitmap, True, bitmap)
            stream.Position = 0
            packet.SetData("PNG", False, stream)
            yield packet

    def write(self, packet):
        from System.Windows.Forms import Clipboard
        from System.Runtime.InteropServices import ExternalException
        try:
            # Flush the data so it survives resource disposal and app shutdown.
            Clipboard.SetDataObject(packet, True, 0, 0)
        except ExternalException:
            raise ClipboardBusy() from None


def dispatch_image(window, operation, stopped, timeout=5):
    """Marshal to WinForms' existing STA; skip callbacks that have timed out."""
    from System import Action
    done, expired, results = threading.Event(), threading.Event(), []
    form = window.native
    if stopped() or form.IsDisposed:
        raise RuntimeError("The app is closing")
    def invoke():
        try:
            if expired.is_set() or stopped() or form.IsDisposed:
                raise RuntimeError("The app is closing")
            results.append(operation())
        except Exception as error:
            results.append(error)
        finally:
            done.set()
    form.BeginInvoke(Action(invoke))
    deadline = time.monotonic() + timeout
    while not done.wait(.05):
        if stopped() or time.monotonic() >= deadline:
            expired.set()
            raise RuntimeError("The clipboard did not respond. Please try again")
    if isinstance(results[0], Exception):
        raise results[0]
    return results[0]


def save_png(png, destination):
    """Replace the explicitly selected destination only after the PNG is complete."""
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
            temporary = file.name
            file.write(png)
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class SummaryImageBridge:
    def __init__(self, window, stopped, preferences, adapter=None, dispatch=None, choose=None):
        self.window, self.stopped, self.preferences = window, stopped, preferences
        self.adapter = adapter or WindowsClipboard()
        self.dispatch = dispatch or dispatch_image
        self.choose = choose
        self.lock = threading.Lock()

    def call(self, action, args=None):
        args = args or {}
        if action not in IMAGE_ACTIONS:
            raise ValueError("Unknown summary image action")
        if self.stopped():
            raise RuntimeError("The app is closing")
        if action == "summary_image_preferences":
            return self.preferences.update(args["include_project_names"]) if "include_project_names" in args else self.preferences.read()
        png = png_payload(args)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A summary image operation is already running")
        try:
            window = self.window()
            if action == "copy_summary_image":
                self.dispatch(window, lambda: copy_to_clipboard(self.adapter, png, self.stopped), self.stopped)
                return {"status": "copied"}
            filename = args.get("filename", "codex-summary.png")
            if not isinstance(filename, str) or not re.fullmatch(r"[\w-]{1,70}\.png", filename, re.ASCII):
                raise ValueError("Choose a PNG filename")
            if self.choose:
                destination = self.choose(window, filename)
            else:
                import webview
                destination = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename, file_types=("PNG image (*.png)",))
            if not destination:
                return {"status": "cancelled"}
            if isinstance(destination, (tuple, list)):
                destination = destination[0]
            if self.stopped():
                raise RuntimeError("The app is closing")
            save_png(png, destination)
            return {"status": "saved"}
        finally:
            self.lock.release()
