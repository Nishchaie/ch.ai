"""Rate limiter for API requests."""

from __future__ import annotations

import time
from collections import deque
from typing import Deque


class RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(
        self,
        max_requests: int = 50,
        window_seconds: float = 60.0,
    ) -> None:
        """
        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Deque[float] = deque()

    def acquire(self) -> None:
        """
        Block until a request slot is available.
        Removes old requests outside the window and waits if at limit.
        """
        now = time.time()

        # Remove requests outside the window
        while self._requests and self._requests[0] < now - self.window_seconds:
            self._requests.popleft()

        # If at limit, wait until the oldest request expires
        if len(self._requests) >= self.max_requests:
            sleep_time = self._requests[0] + self.window_seconds - now
            if sleep_time > 0:
                time.sleep(sleep_time + 0.1)  # Add small buffer
                # Clean up again after sleeping
                now = time.time()
                while self._requests and self._requests[0] < now - self.window_seconds:
                    self._requests.popleft()

        # Record this request
        self._requests.append(time.time())
