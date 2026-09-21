class NotFoundError(Exception):
    """Raised by services when a requested resource doesn't exist. Routers catch
    this and convert it to an HTTP 404 — services never import FastAPI."""
    pass


class ConflictError(Exception):
    """Raised by services for a request that's well-formed but conflicts with
    current state (e.g. starting a session that's already active). Routers
    convert this to an HTTP 400."""
    pass


class ValidationError(Exception):
    """Raised by services when the input itself is unusable (empty plan text, a
    goal outside the allowed range). Distinct from ConflictError: nothing about
    the stored state is wrong, the request is. Routers convert this to an
    HTTP 400, and its message is written to be shown to the student as-is."""
    pass
