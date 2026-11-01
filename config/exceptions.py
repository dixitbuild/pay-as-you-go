from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(Exception):
    """Business-rule violation. Subclasses map to an HTTP 400."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class InvalidTransition(DomainError):
    pass


class InsufficientBalance(DomainError):
    pass


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": exc.message}, status=400)
    return exception_handler(exc, context)
