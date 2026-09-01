"""Signed-URL file download.

The only route that serves private files, and it never trusts the caller: the signature
must match the object key and an unexpired timestamp. This is what stops a leaked
resume path from being a leaked resume.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from app.core.exceptions import InvalidToken, ResourceNotFound
from app.core.logging import get_logger
from app.core.security import verify_storage_signature
from app.providers.storage import get_storage, validate_object_key

logger = get_logger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


@router.get(
    "/download",
    summary="Download a private file with a signed URL",
    description=(
        "Serves a stored document only when the signature and expiry are valid. Signed "
        "URLs are minted by the endpoints that return documents and are short-lived.\n\n"
        "Used only by the local storage backend; S3-compatible storage issues its own "
        "presigned URLs that bypass this route entirely."
    ),
    responses={
        200: {"description": "The file", "content": {"application/octet-stream": {}}},
        401: {"description": "Invalid or expired signature"},
        404: {"description": "File not found"},
    },
)
async def download(
    key: Annotated[str, Query(description="Object key")],
    expires: Annotated[int, Query(description="Unix timestamp the link expires at")],
    signature: Annotated[str, Query(description="HMAC signature")],
) -> Response:
    validate_object_key(key)

    if not verify_storage_signature(key, expires, signature):
        # One message for both a bad signature and an expired one, so a probe cannot
        # distinguish "wrong signature" from "right signature, too late".
        logger.warning("file_download_rejected", reason="invalid_or_expired_signature")
        raise InvalidToken("This download link is invalid or has expired")

    storage = get_storage()
    try:
        content = await storage.get(key)
    except ResourceNotFound:
        raise

    filename = key.rsplit("/", 1)[-1]
    import mimetypes

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def _iter():
        yield content

    return StreamingResponse(
        _iter(),
        media_type=content_type,
        headers={
            # ``attachment`` so a malicious HTML/SVG upload cannot execute in the
            # browser under our origin.
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )
