#!/usr/bin/env python3
"""Serve the property listings dashboard locally for testing before GitHub Pages deploy."""

import argparse
import http.server
import os
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS_PATH = ROOT / "docs"
DATA_FILE = DOCS_PATH / "data" / "property_listings.json"
DEFAULT_PORT = 8000


class LocalDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def run_server(port: int, open_browser: bool) -> None:
    if not DATA_FILE.exists():
        print(f"Warning: {DATA_FILE} not found.")
        print("Run the scraper first:  python scraper.py")
    else:
        print(f"Data file: {DATA_FILE}")

    os.chdir(DOCS_PATH)
    url = f"http://localhost:{port}"

    with socketserver.TCPServer(("", port), LocalDashboardHandler) as httpd:
        print()
        print("Property Listings Dashboard — local server")
        print(f"  URL:     {url}")
        print(f"  Folder:  {DOCS_PATH}")
        print("  Press Ctrl+C to stop")
        print()

        if open_browser:
            webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            httpd.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Serve docs/ dashboard on localhost.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: 8000)")
    parser.add_argument("--open", action="store_true", help="Open browser automatically")
    args = parser.parse_args()
    run_server(args.port, args.open)


if __name__ == "__main__":
    main()
