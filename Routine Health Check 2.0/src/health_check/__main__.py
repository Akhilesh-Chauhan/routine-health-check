"""Allow `python -m health_check` to dispatch the same CLI as `hc`."""
import sys

from health_check.cli import main

if __name__ == "__main__":
    sys.exit(main())
