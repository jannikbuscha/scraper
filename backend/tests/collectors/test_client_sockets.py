"""Client rules that need real sockets (docs/COLLECTORS.md §12.3): a threaded HTTP server
on 127.0.0.1 streams bodies, declares misleading lengths and answers slowly."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

from mdt.collectors import client as client_module
from mdt.collectors.client import RunCancelled
from mdt.collectors.fetchlog import MemorySink
from mdt.collectors.throttle import SystemClock
from tests.collectors.conftest import make_client, make_config


class Handler(BaseHTTPRequestHandler):
    """Routes: /stream (chunked, 64 KiB pieces), /slow (stalls), /trickle-headers (status
    line and headers one byte per 0.25 s, like a tarpit), /page, /robots.txt (404)."""

    def log_message(self, format: str, *args: object) -> None:
        return

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except OSError:  # the client gave up (a size limit, a cut-off trickle)
            self.close_connection = True

    def do_GET(self) -> None:
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(8):
                chunk = b"x" * 65_536
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        elif self.path == "/slow":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"12345")
            self.wfile.flush()
            time.sleep(2.0)
        elif self.path == "/trickle-headers":
            head = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nok"
            try:
                for byte in head:  # every read returns within the read timeout
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.25)
            except OSError:
                pass
            self.close_connection = True
        elif self.path == "/page":
            body = b"<html>local page</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_body_growing_beyond_the_limit_is_aborted(server: str) -> None:
    sink = MemorySink()
    client = make_client(
        httpx2.HTTPTransport(), sink=sink, config=make_config(max_bytes=200_000, min_interval_s=0)
    )
    result = client.get(f"{server}/stream")
    assert result.outcome == "too_large" and result.snapshot is None
    assert sink.snapshots == {}
    assert client.get(f"{server}/page").ok


def test_a_stalled_read_times_out_as_a_network_error(server: str) -> None:
    sink = MemorySink()
    config = make_config(timeout_read_s=0.5, retries=0, min_interval_s=0)
    client = make_client(httpx2.HTTPTransport(), sink=sink, config=config)
    client.clock = SystemClock()
    result = client.get(f"{server}/slow")
    assert result.outcome == "network_error"
    assert "Timeout" in (result.error or "")


def test_trickled_headers_are_cut_off_at_the_request_limit(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "REQUEST_TOTAL_S", 1.0)
    config = make_config(timeout_read_s=1.0, retries=0, min_interval_s=0)
    client = make_client(httpx2.HTTPTransport(), config=config, listing_host=None)
    client.clock = SystemClock()
    started = time.monotonic()
    result = client.get(f"{server}/trickle-headers")
    assert time.monotonic() - started < 5.0  # the headers alone would take about 16 s
    assert result.outcome == "network_error"
    assert "took longer than 1 s" in (result.error or "")
    assert client.get(f"{server}/page").ok  # the client stays usable


def test_trickled_headers_are_cut_off_at_the_manual_fetch_budget(server: str) -> None:
    config = make_config(timeout_read_s=1.0, min_interval_s=0)
    client = make_client(httpx2.HTTPTransport(), config=config, listing_host=None)
    client.clock = SystemClock()
    client.deadline = time.monotonic() + 1.5  # what budget_s=1.5 sets
    started = time.monotonic()
    result = client.get(f"{server}/trickle-headers")
    assert time.monotonic() - started < 5.0
    assert result.outcome == "network_error" and result.out_of_budget
    assert result.reason == "throttled"  # API: 502 fetch_failed {reason: "throttled"}


def test_a_cancel_interrupts_trickled_headers(server: str) -> None:
    cancel = threading.Event()
    config = make_config(timeout_read_s=1.0, min_interval_s=0)
    client = make_client(httpx2.HTTPTransport(), config=config, listing_host=None, cancel=cancel)
    client.clock = SystemClock()
    timer = threading.Timer(0.8, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RunCancelled):
            client.get(f"{server}/trickle-headers")
    finally:
        timer.cancel()
    assert time.monotonic() - started < 4.0
