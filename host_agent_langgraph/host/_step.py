import threading

_lock = threading.Lock()
_counter = 0


def step() -> int:
    global _counter
    with _lock:
        _counter += 1
        return _counter
