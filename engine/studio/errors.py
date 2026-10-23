"""Error types. The `kind` decides retry behaviour in the job runner."""


class StudioError(Exception):
    kind = "unknown"
    retryable = False


class TransientError(StudioError):
    """Network blips, 5xx, timeouts. Safe to retry with backoff."""

    kind = "transient"
    retryable = True


class QuotaError(StudioError):
    """A free allowance is used up. Retry later or use another provider; never pay."""

    kind = "quota"
    retryable = True


class AuthError(StudioError):
    """Invalid/expired credentials. Never retried automatically: the owner must reconnect."""

    kind = "auth"


class ValidationError(StudioError):
    """Output failed a schema or quality gate."""

    kind = "validation"


class PermanentError(StudioError):
    """Will not succeed by retrying (bad input, unsupported feature)."""

    kind = "permanent"


class NeedsReview(StudioError):
    """The system is unsure; a human must look. Not a failure, not retried."""

    kind = "validation"


class BudgetExceeded(StudioError):
    """A paid operation would exceed the owner-approved monthly cap."""

    kind = "quota"


class AmbiguousPublish(StudioError):
    """We cannot tell if a publish succeeded. Never retried blindly (duplicate risk)."""

    kind = "unknown"
