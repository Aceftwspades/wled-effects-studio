"""The studio's entry point - what the packaged app runs, and  python studio.py
from the tree. A popout view is the same exe told to be one (--popout view
block pid), which is how the frozen app opens its second window."""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--popout":
        from native.popout import run
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--doctor":
        from native.doctor import main as doctor
        sys.exit(doctor())
    from native.app import main as app
    app()


if __name__ == "__main__":
    main()
