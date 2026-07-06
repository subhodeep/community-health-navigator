"""GET /api/v1/uploads/signed-url — v4 signed PUT URL for image uploads."""
from __future__ import annotations

import datetime
import functools
import logging
import os
import uuid

import google.auth
from fastapi import APIRouter, Depends, HTTPException, Query
from google.auth.transport import requests as ga_requests
from google.cloud import storage

from auth import User, get_user

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
}
_EXPIRY = datetime.timedelta(minutes=15)


@functools.lru_cache(maxsize=1)
def _storage_client() -> storage.Client:
    return storage.Client()


def _upload_bucket() -> str:
    bucket = os.environ.get("UPLOAD_BUCKET", "")
    if not bucket:
        raise HTTPException(status_code=500, detail="UPLOAD_BUCKET not configured")
    return bucket


def _sign(blob: storage.Blob, content_type: str) -> str:
    """Generate a v4 signed PUT URL, falling back to IAM signBlob when the
    ambient credentials (e.g. Cloud Run compute) carry no private key."""
    kwargs = {
        "version": "v4",
        "expiration": _EXPIRY,
        "method": "PUT",
        "content_type": content_type,
    }
    try:
        return blob.generate_signed_url(**kwargs)
    except (AttributeError, google.auth.exceptions.TransportError):
        credentials, _ = google.auth.default()
        credentials.refresh(ga_requests.Request())
        return blob.generate_signed_url(
            **kwargs,
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )


@router.get("/uploads/signed-url")
def signed_url(
    content_type: str = Query(...), user: User = Depends(get_user)
) -> dict[str, str]:
    """Return {put_url, gcs_uri} for a direct browser PUT of one image."""
    ext = _ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(
            status_code=400,
            detail=f"content_type must be one of {sorted(_ALLOWED_CONTENT_TYPES)}",
        )
    bucket_name = _upload_bucket()
    object_name = f"uploads/{user.user_id}/{uuid.uuid4()}.{ext}"
    blob = _storage_client().bucket(bucket_name).blob(object_name)
    try:
        put_url = _sign(blob, content_type)
    except Exception:
        logger.error("signed URL generation failed", exc_info=True)
        raise HTTPException(status_code=500, detail="could not create upload URL")
    return {"put_url": put_url, "gcs_uri": f"gs://{bucket_name}/{object_name}"}
