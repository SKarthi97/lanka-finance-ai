"""The worker proves it is alive by touching a file; the container health check reads its age."""

import os
import threading
import time

from app import worker


def test_beat_creates_and_refreshes_the_file(tmp_path):
    path = tmp_path / "beat"
    worker.beat(path)
    assert path.exists()
    old = time.time() - 600
    os.utime(path, (old, old))
    worker.beat(path)
    assert time.time() - os.path.getmtime(path) < 5


def test_a_folder_that_cannot_be_written_never_stops_the_worker(tmp_path):
    worker.beat(tmp_path / "missing-folder" / "beat")  # no exception


def test_the_heartbeat_thread_keeps_beating_until_told_to_stop(tmp_path):
    path = tmp_path / "beat"
    stop = threading.Event()
    thread = worker.start_heartbeat(stop, path, every=0.05)
    time.sleep(0.2)
    assert path.exists()
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
