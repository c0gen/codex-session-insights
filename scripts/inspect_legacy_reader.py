"""Retired reader-inspection diagnostic. No executable is inspected."""
import json


def main():
    print(json.dumps({"status": "disabled", "diagnostic": "legacy_collection_disabled",
                      "detail": "Use documented public transcripts and official CLI quota reports."}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
