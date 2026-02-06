"""Token bucket rate limiter for API calls."""

import time
from threading import Lock
from collections import deque


class RateLimiter:
    """Thread-safe token bucket rate limiter.

    Enforces maximum requests per second by tracking timestamps of recent
    requests and blocking (sleeping) when rate limit would be exceeded.

    Attributes:
        max_per_second: Maximum number of requests allowed per second
    """

    def __init__(self, max_per_second: int):
        """Initialize rate limiter.

        Args:
            max_per_second: Maximum requests allowed per second
        """
        self.max_per_second = max_per_second
        self._lock = Lock()
        self._request_times = deque()

    def acquire(self) -> None:
        """Acquire permission to make a request.

        Blocks (sleeps) if making a request would exceed the rate limit.
        Thread-safe.
        """
        with self._lock:
            now = time.time()

            # Remove timestamps older than 1 second (outside the window)
            while self._request_times and now - self._request_times[0] >= 1.0:
                self._request_times.popleft()

            # If at capacity, wait until the oldest request falls outside the window
            if len(self._request_times) >= self.max_per_second:
                # Calculate how long to wait
                sleep_time = 1.0 - (now - self._request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Update 'now' after sleeping
                    now = time.time()
                    # Clean up old timestamps again
                    while self._request_times and now - self._request_times[0] >= 1.0:
                        self._request_times.popleft()

            # Record this request
            self._request_times.append(now)
