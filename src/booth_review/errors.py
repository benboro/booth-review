"""Project exception hierarchy.

Every exception raised by booth_review code (outside third-party libraries)
subclasses BoothReviewError, so callers can catch one type at each layer
boundary (transport, cache, budget, vault, parsing) without enumerating them.
"""

from __future__ import annotations


class BoothReviewError(Exception):
    """Base class for all booth_review exceptions."""


class UnknownHostError(BoothReviewError):
    """Raised when a fetch targets a host outside the configured allow-list."""


class RobotsDisallowedError(BoothReviewError):
    """Raised when robots.txt disallows the requested URL for our user agent."""


class RobotsUnavailableError(BoothReviewError):
    """Raised when robots.txt could not be fetched (5xx or transport failure).

    Fails closed: an unreadable robots.txt is treated as disallow, not allow.
    """


class FetchError(BoothReviewError):
    """Raised for a transport failure after retries, or a non-2xx/304 status
    surfaced by the cache layer.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FrozenSeasonError(BoothReviewError):
    """Raised when a cache miss occurs for a (source, season) marked frozen."""


class EndpointNotAllowedError(BoothReviewError):
    """Raised when a CFBD call targets an endpoint outside the allow-list."""


class BudgetFloorError(BoothReviewError):
    """Raised when a CFBD call would push remaining calls below the floor."""


class BudgetUnknownError(BoothReviewError):
    """Raised when the CFBD remaining-call budget cannot be determined."""


class RunCapError(BoothReviewError):
    """Raised when a run would exceed its configured call cap."""


class MissingApiKeyError(BoothReviewError):
    """Raised when the CFBD API key is absent.

    The message never contains any key text.
    """


class VaultStateError(BoothReviewError):
    """Raised when the data vault is in an unexpected or unusable state."""


class VaultCommitError(BoothReviewError):
    """Raised when committing or pushing the data vault fails."""


class VaultBusyError(VaultStateError):
    """Raised when another booth-review process holds the vault lock past the timeout."""


class FreezeRefusedError(BoothReviewError):
    """Raised when freeze preconditions (completeness, freeze date) are not met."""


class ParseError(BoothReviewError):
    """Raised when a source response cannot be parsed into typed rows."""
