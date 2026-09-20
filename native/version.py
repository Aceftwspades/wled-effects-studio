"""The studio's version, and where its releases live.

The version is what the About dialog shows, what package.py writes into
the bundle, and what the update check compares with the newest release
tag (vX.Y.Z) of REPO. Bump it with each release; the tag is the same
number with a v in front.
"""
__version__ = "1.0.0"
REPO = "Aceftwspades/wled-effects-studio"            # owner/name on GitHub: the releases the update check reads
WLED_REPO = "Aceftwspades/WLED"                       # the WLED fork the firmware side lives in (branch playground)
WLED_UPSTREAM = "Aircoookie/WLED"                     # the WLED project itself


def parse(tag):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); anything else -> None."""
    t = str(tag or "").strip().lstrip("vV")
    try:
        parts = tuple(int(p) for p in t.split("-")[0].split("."))
    except ValueError:
        return None
    return parts if parts else None


def newer(tag):
    """True when the tag names a version after this one."""
    a, b = parse(tag), parse(__version__)
    return bool(a and b and a > b)
