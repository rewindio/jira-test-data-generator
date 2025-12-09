"""
Base classes for Jira API interactions.

Contains rate limiting state, HTTP session management, and core API call logic.
"""

import asyncio
import logging
import random
import string
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import aiohttp
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class RateLimitState:
    """Tracks rate limiting state (shared across async tasks)"""
    retry_after: Optional[float] = None
    consecutive_429s: int = 0
    current_delay: float = 1.0
    max_delay: float = 60.0
    # Lock for thread-safe updates in async context
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Global cooldown - when set, all requests should wait until this time
    _cooldown_until: float = 0.0


class JiraAPIClient:
    """Base class for Jira API interactions with rate limiting and session management."""

    # Pre-generated text pool for high-performance random text generation
    # Shared across all instances to avoid repeated generation
    _TEXT_POOL_SIZE = 1000  # Number of pre-generated text strings per size category
    _text_pool: Optional[Dict[str, List[str]]] = None
    _text_pool_lock = None  # Will be initialized on first use

    # Lorem ipsum words for text generation
    _LOREM_WORDS = [
        'lorem', 'ipsum', 'dolor', 'sit', 'amet', 'consectetur', 'adipiscing', 'elit',
        'sed', 'do', 'eiusmod', 'tempor', 'incididunt', 'ut', 'labore', 'et', 'dolore',
        'magna', 'aliqua', 'enim', 'ad', 'minim', 'veniam', 'quis', 'nostrud',
        'exercitation', 'ullamco', 'laboris', 'nisi', 'aliquip', 'ex', 'ea', 'commodo',
        'consequat', 'duis', 'aute', 'irure', 'in', 'reprehenderit', 'voluptate',
        'velit', 'esse', 'cillum', 'fugiat', 'nulla', 'pariatur', 'excepteur', 'sint',
        'occaecat', 'cupidatat', 'non', 'proident', 'sunt', 'culpa', 'qui', 'officia',
        'deserunt', 'mollit', 'anim', 'id', 'est', 'laborum'
    ]

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark: Optional[Any] = None
    ):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.dry_run = dry_run
        self.concurrency = concurrency
        self.benchmark = benchmark  # Optional BenchmarkTracker for stats

        self.rate_limit = RateLimitState()
        self.session = self._create_session()
        self.logger = logging.getLogger(__name__)

        # Async session (created lazily)
        self._async_session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Initialize text pool on first instance creation
        self._init_text_pool()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic and optimized connection pooling.

        Connection pool settings are tuned for high-throughput API operations:
        - pool_connections: Number of connection pools to cache (per host)
        - pool_maxsize: Maximum connections to save in the pool (per host)
        - pool_block: Whether to block when pool is full (True = wait, False = create new)
        """
        session = requests.Session()

        # Don't retry on 429 - we'll handle that ourselves
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )

        # Optimized connection pooling for high-throughput operations
        # pool_connections=20: Cache up to 20 different host connection pools
        # pool_maxsize=50: Keep up to 50 connections per host ready for reuse
        # This reduces TCP handshake overhead for repeated requests to Jira
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=50,
            pool_block=False  # Don't block, create new connections if pool exhausted
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _record_request(self) -> None:
        """Record a request in benchmark stats."""
        if self.benchmark:
            self.benchmark.record_request()

    def _record_rate_limit(self) -> None:
        """Record a rate limit in benchmark stats."""
        if self.benchmark:
            self.benchmark.record_rate_limit()

    def _record_error(self) -> None:
        """Record an error in benchmark stats."""
        if self.benchmark:
            self.benchmark.record_error()

    def _handle_rate_limit(self, response: requests.Response):
        """Handle rate limit responses intelligently"""
        if response.status_code == 429:
            self.rate_limit.consecutive_429s += 1
            self._record_rate_limit()

            # Check for Retry-After header
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    self.rate_limit.retry_after = float(retry_after)
                except ValueError:
                    # Might be a date string, default to 60s
                    self.rate_limit.retry_after = 60
            else:
                # Use exponential backoff
                self.rate_limit.current_delay = min(
                    self.rate_limit.current_delay * 2,
                    self.rate_limit.max_delay
                )
                self.rate_limit.retry_after = self.rate_limit.current_delay

            self.logger.warning(
                f"Rate limit hit ({self.rate_limit.consecutive_429s} consecutive). "
                f"Waiting {self.rate_limit.retry_after:.1f}s"
            )
            time.sleep(self.rate_limit.retry_after)

        elif response.status_code < 300:
            # Success - reset backoff
            self.rate_limit.consecutive_429s = 0
            self.rate_limit.current_delay = 1.0

    def _api_call(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        max_retries: int = 5,
        base_url: Optional[str] = None
    ) -> Optional[requests.Response]:
        """Make an API call with rate limit handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            data: Request body data
            params: Query parameters
            max_retries: Maximum retry attempts
            base_url: Override base URL (for agile API etc.)
        """
        if base_url is None:
            base_url = f"{self.jira_url}/rest/api/3"
        url = f"{base_url}/{endpoint}"

        if self.dry_run:
            self.logger.info(f"DRY RUN: {method} {endpoint}")
            return None

        for attempt in range(max_retries):
            try:
                self._record_request()
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    auth=(self.email, self.api_token),
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                    timeout=30
                )

                self._handle_rate_limit(response)

                if response.status_code == 429:
                    continue  # Retry after waiting

                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                # Check if this is an "already exists" error (expected when re-running)
                is_already_exists = False
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_text = e.response.text.lower()
                        is_already_exists = 'already exists' in error_text or 'already a member' in error_text
                    except Exception:
                        pass

                if is_already_exists:
                    # Log at debug level - this is expected behavior when re-running
                    self.logger.debug(f"Item already exists: {endpoint}")
                else:
                    self._record_error()
                    self.logger.error(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    # Log response body for errors to help debug
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.text
                            self.logger.error(f"Response body: {error_detail}")
                        except Exception:
                            pass

                # Don't retry on client errors (4xx) - they won't succeed
                if hasattr(e, 'response') and e.response is not None and e.response.status_code < 500:
                    return None
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return None  # Return None instead of raising

        return None

    async def _get_async_session(self) -> aiohttp.ClientSession:
        """Get or create async HTTP session with optimized connection pooling.

        Connection pool settings are tuned for high-throughput async operations:
        - limit: Total number of simultaneous connections
        - limit_per_host: Connections per host (matches our concurrency model)
        - ttl_dns_cache: DNS cache TTL to avoid repeated DNS lookups
        - enable_cleanup_closed: Clean up closed connections promptly
        """
        if self._async_session is None or self._async_session.closed:
            auth = aiohttp.BasicAuth(self.email, self.api_token)
            timeout = aiohttp.ClientTimeout(total=30)

            # Optimized TCP connector for high-throughput operations
            # limit=100: Total connections across all hosts
            # limit_per_host=50: Connections per host (Jira API)
            # ttl_dns_cache=300: Cache DNS for 5 minutes
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=50,
                ttl_dns_cache=300,
                enable_cleanup_closed=True
            )

            self._async_session = aiohttp.ClientSession(
                auth=auth,
                connector=connector,
                timeout=timeout,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            )
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._async_session

    async def _close_async_session(self):
        """Close async HTTP session"""
        if self._async_session and not self._async_session.closed:
            await self._async_session.close()

    async def _handle_rate_limit_async(self, status: int, headers: dict) -> float:
        """Handle rate limit responses in async context. Returns delay if rate limited."""
        if status == 429:
            self._record_rate_limit()
            async with self.rate_limit._lock:
                self.rate_limit.consecutive_429s += 1

                retry_after = headers.get('Retry-After')
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 60
                else:
                    self.rate_limit.current_delay = min(
                        self.rate_limit.current_delay * 2,
                        self.rate_limit.max_delay
                    )
                    delay = self.rate_limit.current_delay

                # Set global cooldown so all requests wait
                self.rate_limit._cooldown_until = time.time() + delay

                self.logger.warning(f"Rate limited. Waiting {delay:.1f}s...")
                return delay
        elif status < 300:
            async with self.rate_limit._lock:
                self.rate_limit.consecutive_429s = 0
                self.rate_limit.current_delay = 1.0
        return 0

    async def _wait_for_cooldown(self) -> None:
        """Wait if we're in a global cooldown period."""
        async with self.rate_limit._lock:
            cooldown_until = self.rate_limit._cooldown_until

        now = time.time()
        if cooldown_until > now:
            wait_time = cooldown_until - now
            await asyncio.sleep(wait_time)

    async def _api_call_async(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        max_retries: int = 5,
        base_url: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict]]:
        """Make an async API call with rate limit handling.

        Returns (success: bool, response_json: Optional[Dict])
        """
        if base_url is None:
            base_url = f"{self.jira_url}/rest/api/3"
        url = f"{base_url}/{endpoint}"

        if self.dry_run:
            self.logger.debug(f"DRY RUN: {method} {endpoint}")
            return (True, None)

        session = await self._get_async_session()

        async with self._semaphore:
            for attempt in range(max_retries):
                # Wait for any global cooldown before making request
                await self._wait_for_cooldown()

                try:
                    self._record_request()
                    async with session.request(method, url, json=data, params=params) as response:
                        delay = await self._handle_rate_limit_async(response.status, dict(response.headers))

                        if response.status == 429:
                            await asyncio.sleep(delay)
                            continue

                        if response.status >= 400:
                            error_text = await response.text()
                            # Check if this is an "already exists" error (expected when re-running)
                            is_already_exists = 'already exists' in error_text.lower() or 'already a member' in error_text.lower()
                            if is_already_exists:
                                self.logger.debug(f"Item already exists: {endpoint}")
                            else:
                                self._record_error()
                                self.logger.error(f"API call failed ({response.status}): {endpoint}")
                                self.logger.error(f"Response: {error_text}")
                            # Don't retry on client errors (4xx) except 429 (rate limit)
                            if response.status < 500:
                                return (False, None)
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            return (False, None)

                        if response.status == 204:
                            return (True, None)

                        result = await response.json()
                        return (True, result)

                except aiohttp.ClientError as e:
                    self._record_error()
                    self.logger.error(f"Async API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return (False, None)

        return (False, None)

    def get_current_user_account_id(self) -> Optional[str]:
        """Get the current user's account ID"""
        if self.dry_run:
            return "dry-run-account-id"

        response = self._api_call('GET', 'myself')
        if response:
            return response.json().get('accountId')
        return None

    def get_all_users(self, max_users: int = 100) -> List[str]:
        """Fetch users from the Jira instance.

        Returns a list of account IDs.
        """
        if self.dry_run:
            return [f"dry-run-user-{i}" for i in range(1, 6)]

        self.logger.info("Fetching users from Jira instance...")

        users = []
        start_at = 0

        while len(users) < max_users:
            response = self._api_call(
                'GET',
                'users/search',
                params={
                    'startAt': start_at,
                    'maxResults': 50
                }
            )

            if not response:
                break

            batch = response.json()
            if not batch:
                break

            for user in batch:
                account_id = user.get('accountId')
                # Filter out inactive users and app users
                if account_id and user.get('active', True) and user.get('accountType') == 'atlassian':
                    users.append(account_id)

            if len(batch) < 50:
                break

            start_at += 50

        self.logger.info(f"Found {len(users)} users")
        return users[:max_users]

    @classmethod
    def _init_text_pool(cls) -> None:
        """Initialize the pre-generated text pool.

        Creates pools of random text strings in different size categories
        that can be quickly retrieved instead of generating on each call.
        This significantly reduces CPU overhead at scale (millions of items).

        Size categories match common usage patterns:
        - short (3-10 words): comments, component descriptions
        - medium (5-15 words): issue descriptions, property descriptions
        - long (10-30 words): detailed descriptions
        """
        if cls._text_pool is not None:
            return  # Already initialized

        import threading
        if cls._text_pool_lock is None:
            cls._text_pool_lock = threading.Lock()

        with cls._text_pool_lock:
            # Double-check after acquiring lock
            if cls._text_pool is not None:
                return

            logging.getLogger(__name__).debug(
                f"Pre-generating {cls._TEXT_POOL_SIZE * 3} random text strings..."
            )

            cls._text_pool = {
                'short': [],   # 3-10 words
                'medium': [],  # 5-15 words
                'long': []     # 10-30 words
            }

            # Generate short texts (3-10 words)
            for _ in range(cls._TEXT_POOL_SIZE):
                num_words = random.randint(3, 10)
                text = ' '.join(random.choices(cls._LOREM_WORDS, k=num_words)).capitalize()
                cls._text_pool['short'].append(text)

            # Generate medium texts (5-15 words)
            for _ in range(cls._TEXT_POOL_SIZE):
                num_words = random.randint(5, 15)
                text = ' '.join(random.choices(cls._LOREM_WORDS, k=num_words)).capitalize()
                cls._text_pool['medium'].append(text)

            # Generate long texts (10-30 words)
            for _ in range(cls._TEXT_POOL_SIZE):
                num_words = random.randint(10, 30)
                text = ' '.join(random.choices(cls._LOREM_WORDS, k=num_words)).capitalize()
                cls._text_pool['long'].append(text)

    @classmethod
    def generate_random_text(cls, min_words: int = 5, max_words: int = 20) -> str:
        """Get random lorem ipsum style text from pre-generated pool.

        Uses pre-generated text pools for performance. Falls back to
        generating on-the-fly if pool isn't initialized (shouldn't happen
        in normal usage).

        Args:
            min_words: Minimum word count (used to select pool category)
            max_words: Maximum word count (used to select pool category)

        Returns:
            Random text string from the appropriate pool
        """
        # Ensure pool is initialized
        if cls._text_pool is None:
            cls._init_text_pool()

        # Select pool based on requested size range
        avg_words = (min_words + max_words) // 2

        if avg_words <= 7:
            pool = cls._text_pool['short']
        elif avg_words <= 12:
            pool = cls._text_pool['medium']
        else:
            pool = cls._text_pool['long']

        return random.choice(pool)
