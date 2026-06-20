"""Custom DRF exception handler."""

from __future__ import annotations

import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Wrap DRF default handler with logging."""
    response = exception_handler(exc, context)
    if response is not None:
        logger.warning("API exception: %s — %s", type(exc).__name__, exc)
    return response
