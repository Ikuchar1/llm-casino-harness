"""Serve the showcase demo and keep its live board (standard library only).

Usage (from the repo root):
    .venv/bin/python scripts/demo_server.py            # http://localhost:8000
    .venv/bin/python scripts/demo_server.py --port 8080

Serves demo/ (the page is demo/index.html) on localhost only, plus two endpoints:

    POST /api/results   {"deals": [{"id": "hard16_vs_10", "action": "hit"}, ...]}
        One visitor's graded first decisions. The server re-grades each one against
        basic strategy from demo/demo_data.json and appends one line to
        demo/visitor_results.jsonl: {ts, deals, actions, correct}. Nothing personal
        is stored. Replies with the board.
    GET  /api/board
        Visitor accuracy, and the baseline and full harness seats' accuracy over the
        same deals (each deal counted once per visitor who played it), with counts.

The board is recomputed from the jsonl file on every request, so it survives a
restart. demo_data.json is re-read when its modification time changes, so a fresh
scripts/export_demo_data.py shows up without restarting the server.
"""

import argparse
import json
import os
import sys
import threading
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo"
DEFAULT_DATA = DEMO_DIR / "demo_data.json"
DEFAULT_RESULTS = DEMO_DIR / "visitor_results.jsonl"
DEFAULT_PORT = 8000
MAX_DEALS_PER_VISITOR = 10
MAX_BODY_BYTES = 16_384
SEATS = ("baseline", "full")


# ---------- the board math (pure functions, tested directly) ----------


def read_results(path: Path) -> list[dict[str, Any]]:
    """Every visitor line in the results file. A broken line (a crash mid-write) is skipped."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("deals"), list) and isinstance(row.get("correct"), list):
            rows.append(row)
    return rows


def _tally(correct: int, total: int) -> dict[str, Any]:
    return {"correct": correct, "total": total, "accuracy": correct / total if total else None}


def compute_board(data: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate accuracy over every visitor deal.

    Each agent seat is scored on the deals visitors actually played (a deal played by
    five visitors counts five times), so the three bars are over the same hands. A
    deal the seat has not answered yet is left out of that seat's count.
    """
    by_id = {s["id"]: s for s in data.get("scenarios", [])}
    visitor = [0, 0]
    seats = {seat: [0, 0] for seat in SEATS}
    distinct = set()
    for row in results:
        for deal_id, ok in zip(row["deals"], row["correct"]):
            scenario = by_id.get(deal_id)
            if scenario is None:
                continue
            distinct.add(deal_id)
            visitor[0] += bool(ok)
            visitor[1] += 1
            for seat in SEATS:
                entry = scenario["seats"][seat]
                if entry.get("status") == "answered":
                    seats[seat][0] += bool(entry["correct"])
                    seats[seat][1] += 1
    return {
        "visitors": len(results),
        "deals_played": visitor[1],
        "distinct_deals": len(distinct),
        "visitor": _tally(*visitor),
        **{seat: _tally(*seats[seat]) for seat in SEATS},
    }


def grade_submission(data: dict[str, Any], body: Any) -> dict[str, Any]:
    """Check a POST body and turn it into the line to store. Raises ValueError if bad."""
    if not isinstance(body, dict) or not isinstance(body.get("deals"), list):
        raise ValueError('body must be {"deals": [{"id": ..., "action": ...}, ...]}')
    deals = body["deals"]
    if not 1 <= len(deals) <= MAX_DEALS_PER_VISITOR:
        raise ValueError(f"send between 1 and {MAX_DEALS_PER_VISITOR} deals")
    by_id = {s["id"]: s for s in data.get("scenarios", [])}
    ids, actions, correct = [], [], []
    for deal in deals:
        if not isinstance(deal, dict):
            raise ValueError("each deal must be an object")
        deal_id = deal.get("id")
        if not isinstance(deal_id, str):
            raise ValueError("each deal id must be a string")
        scenario = by_id.get(deal_id)
        if scenario is None:
            raise ValueError(f"unknown deal id {deal.get('id')!r}")
        action = deal.get("action")
        if action not in scenario["legal"]:
            raise ValueError(f"{action!r} is not a legal first action for {scenario['id']}")
        ids.append(scenario["id"])
        actions.append(action)
        correct.append(action == scenario["basic"])
    if len(set(ids)) != len(ids):
        raise ValueError("a visitor plays each deal once")
    return {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "deals": ids,
            "actions": actions, "correct": correct}


# ---------- the server ----------


class DemoStore:
    """demo_data.json (reloaded when it changes) and the append-only results file."""

    def __init__(self, data_path: Path, results_path: Path):
        self.data_path = Path(data_path)
        self.results_path = Path(results_path)
        self.lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._mtime: Optional[float] = None

    def data(self) -> dict[str, Any]:
        with self.lock:
            try:
                mtime = self.data_path.stat().st_mtime
            except FileNotFoundError:
                return {"scenarios": []}
            if mtime != self._mtime:
                self._data = json.loads(self.data_path.read_text(encoding="utf-8"))
                self._mtime = mtime
            return self._data

    def append(self, row: dict[str, Any]) -> None:
        with self.lock:
            self.results_path.parent.mkdir(parents=True, exist_ok=True)
            with self.results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()

    def board(self) -> dict[str, Any]:
        data = self.data()
        with self.lock:
            results = read_results(self.results_path)
        return compute_board(data, results)


class DemoHandler(SimpleHTTPRequestHandler):
    store: DemoStore  # set by make_server

    # The results file lives in demo/ but is never served, nor is any other .jsonl or a
    # half-written .tmp. Checked on the resolved file path, so "/./x" or "%76" spellings
    # of a hidden name are caught too.
    HIDDEN_SUFFIXES = (".jsonl", ".tmp")

    def _hidden(self) -> bool:
        real = os.path.realpath(self.translate_path(self.path))
        if real.endswith(self.HIDDEN_SUFFIXES):
            return True
        return real == os.path.realpath(self.store.results_path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/"):
            super().log_message(format, *args)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/board":
            return self._json(HTTPStatus.OK, self.store.board())
        if path.startswith("/api/") or self._hidden():
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return super().do_GET()

    def do_HEAD(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") or self._hidden():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/results":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("missing or oversized body")
            body = json.loads(self.rfile.read(length))
            row = grade_submission(self.store.data(), body)
        except (TypeError, ValueError) as error:  # json.JSONDecodeError is a ValueError
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        self.store.append(row)
        return self._json(HTTPStatus.OK, {"stored": row, "board": self.store.board()})

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    host: str = "127.0.0.1", port: int = DEFAULT_PORT, data_path: Path = DEFAULT_DATA,
    results_path: Path = DEFAULT_RESULTS, directory: Path = DEMO_DIR,
) -> ThreadingHTTPServer:
    store = DemoStore(data_path, results_path)
    handler = type("BoundDemoHandler", (DemoHandler,), {"store": store})
    server = ThreadingHTTPServer((host, port), partial(handler, directory=str(directory)))
    server.daemon_threads = True
    server.store = store  # type: ignore[attr-defined]
    return server


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the showcase demo on localhost.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1, this machine only)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="demo data (default demo/demo_data.json)")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS,
                        help="visitor results file (default demo/visitor_results.jsonl)")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.data.exists():
        print(f"ERROR: {args.data} not found. Run scripts/export_demo_data.py first.", file=sys.stderr)
        return 1
    server = make_server(args.host, args.port, args.data, args.results)
    board = server.store.board()  # type: ignore[attr-defined]
    print(f"Demo at http://localhost:{args.port}/  ({board['visitors']} visitors so far, results in {args.results})")
    print("Presenter mode: Shift+Alt+P on the page, or open http://localhost:%d/#presenter" % args.port)
    print("Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
