"""Opt-in config edits with preview and compare-before-restore ownership."""
import json
import shlex
import subprocess
import sys
from pathlib import Path

from .bridge_io import MAX_INPUT, locked, write_json
from .bridge_command import default_command, require_helper
from .profiles import config_directory, root_key
from ..codec import digest

HOOK_NAME = "codex-session-insights"
TARGETS = ("claude_code", "antigravity", "antigravity_cli")


def read_json(path):
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_INPUT:
        raise ValueError("Configuration too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object")
    return value


class Setup:
    def __init__(self, directory, home=None, command=None):
        self.directory = Path(directory)
        self.home = Path(home) if home else Path.home()
        self.state_path = self.directory / "bridge" / "setup.json"
        self.helper = None
        if command is None:
            command, self.helper = default_command()
        self.command = command

    def path(self, target):
        if target == "claude_code":
            return config_directory(self.home) / "settings.json"
        if target == "antigravity_cli":
            return self.home / ".gemini" / "antigravity-cli" / "settings.json"
        if target == "antigravity":
            return self.home / ".gemini" / "config" / "hooks.json"
        raise ValueError("Unsupported setup target")

    def state_key(self, target, path=None):
        if target == 'claude_code':
            return target + ":" + digest(root_key(path or self.path(target)))
        return target

    def ownership_states(self):
        states = read_json(self.state_path)
        # Before profile support, Claude setup always edited ~/.claude.
        legacy = states.pop("claude_code", None)
        if legacy is not None:
            key = self.state_key("claude_code", self.home / ".claude" / "settings.json")
            states.setdefault(key, legacy)
        return states

    def previous_file(self, target):
        return self.directory / "bridge" / (self.state_key(target).replace(":", "-") + "-previous.json")

    def shell_command(self, target, event=None):
        provider = "claude_code" if target == "claude_code" else "antigravity"
        args = self.command + ["--data-dir", str(self.directory), "--provider", provider,
                               "--mode", "hook" if event else "status"]
        if event:
            args += ["--event", event]
        else:
            args += ["--previous-file", str(self.previous_file(target))]
        if sys.platform == 'win32' and provider == 'antigravity':
            from .windows_launcher import command
            return command(args)
        return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)

    def desired(self, target, existing):
        if target == "antigravity":
            return {"PostInvocation": [{"type": "command", "command": self.shell_command(target, "PostInvocation"), "timeout": 5}],
                    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": self.shell_command(target, "PostToolUse"), "timeout": 5}]}]}
        result = dict(existing) if isinstance(existing, dict) else {}
        result.update(type="command", command=self.shell_command(target))
        if target == "antigravity_cli":
            result.update(enabled=True)
        return result

    def preview(self, target, check_helper=True):
        if check_helper:
            require_helper(self.helper)
        path = self.path(target)
        config = read_json(path)
        key = HOOK_NAME if target == "antigravity" else "statusLine"
        state = self.ownership_states().get(self.state_key(target), {})
        existing = config.get(key)
        owned = state.get("installed") is not None and existing == state["installed"]
        desired = self.desired(target, existing)
        return {"target": target, "path": str(path), "key": key,
                "configuration": desired, "installed": owned, 'upgrade_available': owned and existing != desired,
                "conflict": target == "antigravity" and existing is not None and not owned,
                "status": "installed" if owned else state.get("status", "not_installed"),
                "preserves_existing_output": target != "antigravity" and bool(existing)}

    def update(self, target, operation):
        if operation not in {"install", "disable", "uninstall"}:
            raise ValueError("Unsupported setup operation")
        with locked(self.directory / "bridge"):
            preview = self.preview(target, check_helper=operation == "install")
            config = read_json(self.path(target))
            states = self.ownership_states()
            state_key = self.state_key(target)
            state = states.get(state_key, {})
            key = preview["key"]
            if operation == "install":
                if preview["installed"]:
                    if preview['upgrade_available']:
                        if target != 'antigravity':
                            write_json(self.previous_file(target), state.get('previous'))
                        state['installed'] = preview['configuration']
                        states[state_key] = state
                        write_json(self.state_path, states)
                        config[key] = state['installed']
                        write_json(self.path(target), config)
                    return self.preview(target)
                if preview["conflict"]:
                    raise ValueError("Hook name already in use; existing configuration preserved")
                previous = config.get(key)
                if target != "antigravity":
                    if previous is not None and (not isinstance(previous, dict) or previous.get("type") != "command"):
                        raise ValueError("Cannot safely preserve this status-line type")
                    if isinstance(previous, dict) and previous.get("command") == self.shell_command(target):
                        raise ValueError("Bridge ownership record missing; existing configuration preserved")
                    write_json(self.previous_file(target), previous)
                state = {"previous": previous, "installed": preview["configuration"], "status": "installed"}
                # Save ownership before config mutation so an interruption is recoverable.
                states[state_key] = state
                write_json(self.state_path, states)
                config[key] = state["installed"]
                write_json(self.path(target), config)
            else:
                if preview["installed"]:
                    if state.get("previous") is None:
                        config.pop(key, None)
                    else:
                        config[key] = state["previous"]
                    write_json(self.path(target), config)
                states[state_key] = {**state, "status": "disabled" if operation == "disable" else "not_installed"}
                states[state_key].pop("installed", None)
                write_json(self.state_path, states)
            return self.preview(target, check_helper=operation == "install")

    def states(self):
        result = []
        for target in TARGETS:
            try:
                result.append(self.preview(target))
            except (OSError, ValueError) as exc:
                result.append({"target": target, "status": "unavailable", "error": str(exc)})
        return result
