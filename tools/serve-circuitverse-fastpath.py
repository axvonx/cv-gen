"""Build the pinned local frontend and serve compiled packages on localhost."""

import argparse
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastpath.compiler import ROOT
from fastpath.frontend_build import prepare


def server(frontend, packages, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            root, relative = (
                (packages, path[len("/packages/") :])
                if path.startswith("/packages/")
                else (frontend, path.removeprefix("/simulator/").lstrip("/"))
            )
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()):
                self.send_error(403)
                return
            if path in {"/", "/simulator", "/simulator/"}:
                target = frontend / "index.html"
            if (
                not target.is_file()
                and root == frontend
                and path.startswith("/simulator/")
                and not Path(relative).suffix
            ):
                target = frontend / "index.html"
            if not target.is_file():
                self.send_error(404)
                return
            self.send_response(200)
            mime = "text/javascript" if target.suffix == ".mjs" else mimetypes.guess_type(target)[0]
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(target.read_bytes())

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=ROOT / "build/fastpath")
    parser.add_argument("--frontend", type=Path, default=ROOT / "build/fastpath/frontend")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    frontend = args.frontend / "dist/simulatorvue/v0" if args.no_build else prepare(args.frontend)
    http = server(frontend.resolve(), args.packages.resolve(), args.port)
    print(f"http://127.0.0.1:{http.server_port}/simulator?fastpath=/packages/cpu/", flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()


if __name__ == "__main__":
    main()
