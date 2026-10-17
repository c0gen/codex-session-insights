"""Explain missing public history without treating saved artifacts as activity."""


def missing_history(provider, kind, discovered_files):
    if provider != "antigravity" or kind != "folder" or discovered_files:
        return None
    return {"status": "No supported history", "detail":
        "No supported transcripts found at <conversation>/.system_generated/logs/transcript.jsonl. "
        "Brain folders containing only plans, tasks, walkthroughs or other saved artifacts "
        "cannot supply session or token accounting. Encrypted archive collection is disabled. "
        "Enable the passive Antigravity bridge "
        "in Sources for future activity on clients that support documented hooks. "
        "Previously indexed history is retained."}
