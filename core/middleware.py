"""Request middleware for the core app."""

import secrets

from core.logging import current_ref

# No 0/O or 1/I/L, so a reference is easy to read out over the phone.
REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
REF_LENGTH = 6


def new_ref() -> str:
    """Make a short, random, easy-to-read reference for one request."""
    return "".join(secrets.choice(REF_ALPHABET) for _ in range(REF_LENGTH))


class RequestRefMiddleware:
    """Give every request a reference shown on error pages and written to the logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """Set the reference for this request."""
        request.ref = new_ref()
        # Not reset afterwards: Django logs 4xx/5xx responses after they leave the
        # middleware, and those lines need the reference too. The next request replaces it.
        current_ref.set(request.ref)
        response = self.get_response(request)
        response["X-Request-Ref"] = request.ref
        return response
