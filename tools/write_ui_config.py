"""Write ui/js/config.js: the two service addresses the static UI calls.

The deployment runs this before uploading ui/ to Azure Storage, with the Container Apps
addresses; locally the committed config.js (localhost:8001 and :8002) is used as it is.

    uv run tools/write_ui_config.py --vehicles-url https://... --reservations-url https://...
"""
import argparse
import json
import pathlib
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "ui" / "js" / "config.js"
LOCAL_HOSTS = ("localhost", "127.0.0.1")


def check_url(name, url):
    """Return the URL without a trailing slash, or raise ValueError if it is not usable."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{name} must be a full http(s) address, got {url!r}")
    if parsed.hostname not in LOCAL_HOSTS and "." not in parsed.hostname:
        # e.g. "https://8001": a port typed where the host name should be
        raise ValueError(f"{name} needs a host name such as app.azurecontainerapps.io, got {url!r}")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        # the UI is served over https in Azure, and a browser blocks http calls from it
        raise ValueError(f"{name} must use https outside localhost, got {url!r}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not have a query or fragment, got {url!r}")
    return url.rstrip("/")


def render(vehicles_url, reservations_url):
    # json.dumps writes valid, escaped JavaScript string literals
    return (
        "// Written by tools/write_ui_config.py. Where the two services are.\n"
        "window.RUTA7_CONFIG = {\n"
        f"  vehiclesUrl: {json.dumps(vehicles_url)},\n"
        f"  reservationsUrl: {json.dumps(reservations_url)},\n"
        "};\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vehicles-url", required=True)
    parser.add_argument("--reservations-url", required=True)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        content = render(
            check_url("--vehicles-url", args.vehicles_url),
            check_url("--reservations-url", args.reservations_url),
        )
    except ValueError as error:
        parser.error(str(error))
    args.out.write_text(content)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()