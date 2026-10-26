"""Hứng Đồ v2 entry point.

Usage: python main.py [--autoplay] [--smoke-seconds N] [--start-scene NAME] [--data-dir DIR]
"""
import os
import sys

# Make `import game` work no matter what the cwd is
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game.app import App, setup_logging, write_crash_log  # noqa: E402


def main() -> int:
    try:
        app = App()
    except Exception as e:
        # App.run() logs its own crashes; this covers start-up failures
        setup_logging()
        write_crash_log(e)
        raise
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
