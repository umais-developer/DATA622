"""
cloud_storage.py - Google Cloud Storage Persistence Layer

Syncs local data/models/outputs to GCS so Cloud Run containers
can restore state after restart.

Environment variables:
  PHARMACAST_GCS_BUCKET  - bucket name (required for GCS sync)
  PHARMACAST_GCS_PREFIX  - optional prefix/subfolder in bucket (default: "")
"""

import os
import logging

logger = logging.getLogger(__name__)

_SYNC_DIRS = ["data", "models", "outputs"]
_SYNC_FILES = ["pharmacy_config.yaml"]

GCS_BUCKET_NAME = os.environ.get("PHARMACAST_GCS_BUCKET", "")
GCS_PREFIX = os.environ.get("PHARMACAST_GCS_PREFIX", "").strip("/")


def is_gcs_enabled() -> bool:
    return bool(GCS_BUCKET_NAME)


def _get_client():
    try:
        from google.cloud import storage
        return storage.Client()
    except Exception as e:
        logger.warning("GCS client unavailable: %s", e)
        return None


def _blob_name(local_path: str) -> str:
    rel = local_path.replace("\\", "/")
    if GCS_PREFIX:
        return f"{GCS_PREFIX}/{rel}"
    return rel


def download_from_gcs() -> bool:
    """Download persisted files from GCS, overwriting local demo files.
    Returns True if any files were downloaded."""
    if not is_gcs_enabled():
        logger.info("GCS not configured, using baked-in demo data.")
        return False

    client = _get_client()
    if client is None:
        return False

    bucket = client.bucket(GCS_BUCKET_NAME)
    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""

    blobs = list(bucket.list_blobs(prefix=prefix or None))
    if not blobs:
        logger.info("GCS bucket is empty, using baked-in demo data.")
        return False

    downloaded = 0
    for blob in blobs:
        if GCS_PREFIX:
            local_rel = blob.name[len(GCS_PREFIX) + 1:]
        else:
            local_rel = blob.name

        if not local_rel:
            continue

        local_path = os.path.join(".", local_rel)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        blob.download_to_filename(local_path)
        downloaded += 1

    logger.info("Downloaded %d files from GCS bucket '%s'.", downloaded, GCS_BUCKET_NAME)
    return downloaded > 0


def upload_to_gcs() -> int:
    """Upload all data/models/outputs and config to GCS.
    Returns the number of files uploaded."""
    if not is_gcs_enabled():
        logger.info("GCS not configured, skipping upload.")
        return 0

    client = _get_client()
    if client is None:
        return 0

    bucket = client.bucket(GCS_BUCKET_NAME)
    uploaded = 0

    for dir_name in _SYNC_DIRS:
        if not os.path.isdir(dir_name):
            continue
        for root, _dirs, files in os.walk(dir_name):
            for fname in files:
                local_path = os.path.join(root, fname)
                blob_name = _blob_name(local_path)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(local_path)
                uploaded += 1

    for fpath in _SYNC_FILES:
        if os.path.exists(fpath):
            blob_name = _blob_name(fpath)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(fpath)
            uploaded += 1

    logger.info("Uploaded %d files to GCS bucket '%s'.", uploaded, GCS_BUCKET_NAME)
    return uploaded
