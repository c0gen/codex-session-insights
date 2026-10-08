import sys
from codex_insights.cli import main

if __name__ == '__main__':
    args=sys.argv[1:]
    if not args:
        args=['exporter']
    raise SystemExit(main(args))
