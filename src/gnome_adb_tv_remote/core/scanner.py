"""
Subnet Scanner for discovering Android TV devices.

Provides concurrent TCP port scanning to find devices with ADB enabled
on port 5555. Uses a thread pool for parallel scanning with progress
and discovery callbacks.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ScanProgress:
    scanned: int
    total: int


@dataclass(frozen=True)
class HostFound:
    ip: ipaddress.IPv4Address
    port: int
    latency_ms: float


class SubnetScanner:
    def __init__(
        self,
        *,
        port: int = 5555,
        timeout_s: float = 0.25,  # Reduced from 0.35s for faster scans on local networks
        concurrency: int = 256,
    ) -> None:
        self._port = port
        self._timeout_s = timeout_s
        self._concurrency = max(1, int(concurrency))

    def scan(
        self,
        networks: list[ipaddress.IPv4Network],
        *,
        cancel_event: threading.Event | None = None,
        on_progress: Callable[[ScanProgress], None] | None = None,
        on_found: Callable[[HostFound], None] | None = None,
    ) -> None:
        """Scan networks for hosts with TCP port open.

        This is blocking; run it in a worker thread. Callbacks are invoked from the
        scanning thread.
        """
        if cancel_event is None:
            cancel_event = threading.Event()

        hosts: list[ipaddress.IPv4Address] = []
        for n in networks:
            # Safety: never scan non-private ranges
            if not n.is_private:
                continue
            hosts.extend([ip for ip in n.hosts()])

        total = len(hosts)
        scanned = 0

        def probe(ip: ipaddress.IPv4Address) -> HostFound | None:
            if cancel_event and cancel_event.is_set():
                return None

            t0 = time.monotonic()
            try:
                with socket.create_connection((str(ip), self._port), timeout=self._timeout_s):
                    pass
                latency_ms = (time.monotonic() - t0) * 1000.0
                return HostFound(ip=ip, port=self._port, latency_ms=latency_ms)
            except (TimeoutError, socket.timeout, OSError):
                return None

        ex = ThreadPoolExecutor(max_workers=self._concurrency)
        try:
            futures = [ex.submit(probe, ip) for ip in hosts]
            for fut in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)
                    return

                res = fut.result()
                scanned += 1

                if on_progress:
                    on_progress(ScanProgress(scanned=scanned, total=total))

                if res and on_found:
                    on_found(res)
        finally:
            # Normal completion: wait for worker threads to finish cleanly.
            ex.shutdown(wait=True, cancel_futures=True)


