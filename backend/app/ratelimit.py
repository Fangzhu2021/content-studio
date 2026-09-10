"""登录失败限流（进程内实现，单机部署足够；多实例时换 Redis）"""
import time

WINDOW_SEC = 300
MAX_FAILS = 5

_fails: dict[str, list[float]] = {}


def _prune(key: str) -> list[float]:
    now = time.time()
    items = [t for t in _fails.get(key, []) if now - t < WINDOW_SEC]
    if items:
        _fails[key] = items
    else:
        _fails.pop(key, None)
    return items


def is_blocked(key: str) -> tuple[bool, int]:
    items = _prune(key)
    if len(items) >= MAX_FAILS:
        retry = int(WINDOW_SEC - (time.time() - items[0])) + 1
        return True, max(retry, 1)
    return False, 0


def record_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def clear(key: str) -> None:
    _fails.pop(key, None)
