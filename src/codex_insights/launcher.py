"""Catch startup failures before importing the app or native dependencies."""
import logging
import os
import platform
import sys
import tempfile
from pathlib import Path

from . import __version__
from .paths import default_directory


def log_directory(argv):
    for index, arg in enumerate(argv):
        if arg.startswith("--data-dir="):
            return Path(arg.split("=", 1)[1]).expanduser()
        if arg == "--data-dir" and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser()
    return default_directory()


def open_startup_log(directory):
    # Fall back to a private temporary location if the chosen index path fails.
    for target in (directory, Path(tempfile.gettempdir()) / "Codex Session Insights"):
        try:
            target.mkdir(parents=True, exist_ok=True)
            path = target / "startup.log"
            if path.exists() and path.stat().st_size > 256 * 1024:
                try:
                    path.replace(target / "startup.previous.log")
                except OSError:
                    pass
            return path, path.open("a", encoding="utf-8", buffering=1)
        except OSError:
            continue
    return None, None


def show_startup_error(error, log_path):
    if platform.system() != "Windows":
        return
    import ctypes
    details = f"\n\nStartup details: {log_path}" if log_path else ""
    ctypes.windll.user32.MessageBoxW(
        0, f"Couldn’t open Codex Session Insights.\n\n{error}{details}",
        "Codex Session Insights", 0x10,
    )


def launch(argv=None, default_command="gui"):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and default_command != "gui":
        arguments = [default_command]
    log_path, stream = open_startup_log(log_directory(arguments))
    handler = logging.StreamHandler(stream) if stream else logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger()
    prior_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    null_stream = None
    if sys.stdout is None or sys.stderr is None:
        null_stream = open(os.devnull, "w") if stream is None else None
        sys.stdout = sys.stdout or stream or null_stream
        sys.stderr = sys.stderr or stream or null_stream
    try:
        logging.info("Starting Codex Session Insights %s (%s, Python %s)",
                     __version__, platform.system(), platform.python_version())
        from .cli import main
        code = main(arguments)
        logging.info("App exited with code %s", code)
        return code
    except Exception as error:
        logging.exception("App startup or command failed")
        if sys.stderr:
            print(str(error), file=sys.stderr)
        headless = {"scan", "export", "import", "report", "catalog", "serve", "diagnose-antigravity-legacy"}
        automated = "--smoke-result" in arguments or os.environ.get("CODEX_INSIGHTS_SMOKE_RESULT")
        if not any(arg in headless for arg in arguments) and not automated and "--diagnose" not in arguments:
            show_startup_error(error, log_path)
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(prior_level)
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if stream:
            stream.close()
        if null_stream:
            null_stream.close()
