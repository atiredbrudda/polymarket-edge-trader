"""Tests for rate limiting behavior."""

import time
from datetime import datetime
from threading import Thread

import pytest

from src.api.rate_limiter import RateLimiter


class TestRateLimiter:
    """Test suite for RateLimiter token bucket implementation."""

    def test_rate_limiter_allows_within_limit(self):
        """Test that requests within rate limit proceed without delay."""
        limiter = RateLimiter(max_per_second=5)

        start = time.time()
        # Make 3 requests - should all proceed immediately since limit is 5/s
        for _ in range(3):
            limiter.acquire()
        elapsed = time.time() - start

        # Should complete in under 100ms (virtually instant)
        assert elapsed < 0.1, f"Expected instant completion, took {elapsed:.3f}s"

    def test_rate_limiter_blocks_over_limit(self):
        """Test that burst exceeding max_per_second gets delayed."""
        limiter = RateLimiter(max_per_second=5)

        start = time.time()
        # Make 6 requests (1 over limit)
        for _ in range(6):
            limiter.acquire()
        elapsed = time.time() - start

        # Should be delayed by at least the token bucket refill time
        # With 5/s, the 6th request should wait ~0.2s (1/5)
        assert elapsed >= 0.15, f"Expected delay for 6th request, completed in {elapsed:.3f}s"

    def test_rate_limiter_resets_after_window(self):
        """Test that rate limiter resets after time window passes."""
        limiter = RateLimiter(max_per_second=3)

        # Fill the bucket
        for _ in range(3):
            limiter.acquire()

        # Wait for window to pass (1 second + margin)
        time.sleep(1.1)

        # Next requests should proceed without delay
        start = time.time()
        for _ in range(3):
            limiter.acquire()
        elapsed = time.time() - start

        assert elapsed < 0.1, f"Expected instant after window reset, took {elapsed:.3f}s"

    def test_rate_limiter_thread_safe(self):
        """Test that rate limiter is thread-safe."""
        limiter = RateLimiter(max_per_second=10)

        results = []

        def make_request():
            limiter.acquire()
            results.append(time.time())

        # Create 20 threads (2x the limit)
        threads = [Thread(target=make_request) for _ in range(20)]

        start = time.time()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.time() - start

        # Should take at least 1 second (10 requests/s, 20 requests = 2 seconds minimum)
        # But allow some margin for thread scheduling
        assert elapsed >= 0.9, f"Expected at least 1s for 20 requests at 10/s, took {elapsed:.3f}s"
        assert len(results) == 20, "All threads should complete"
