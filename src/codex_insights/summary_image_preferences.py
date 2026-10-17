"""A tiny native preference, independent of the index and ephemeral web origins."""
import json
import os
from pathlib import Path
import tempfile
import threading


class SummaryImagePreferences:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.value = isinstance(saved, dict) and saved.get("include_project_names") is True
        except (OSError, ValueError):
            self.value = False

    def read(self):
        with self.lock:
            return {"include_project_names": self.value}

    def update(self, value):
        if type(value) is not bool:
            raise ValueError("Choose whether to include project names")
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            name = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
                    name = file.name
                    json.dump({"include_project_names": value}, file)
                os.replace(name, self.path)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
            self.value = value
            return {"include_project_names": value}
