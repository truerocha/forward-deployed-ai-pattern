"""
S3 utilities with failure classification.

Classifies S3 errors as retriable (throttle, timeout) vs permanent
(access denied, bucket not found) and retries appropriately.

Fixes: Pipeline loose end #5 — S3 write failures are silently swallowed,
creating gaps in the audit trail.
"""
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

logger = logging.getLogger("fde.s3_utils")

# Retriable error codes (transient — will likely succeed on retry)
_RETRIABLE_CODES = {
    "Throttling",
    "SlowDown",
    "RequestTimeout",
    "InternalError",
    "ServiceUnavailable",
    "RequestTimeTooSkewed",
}

# Permanent error codes (won't succeed on retry — configuration issue)
_PERMANENT_CODES = {
    "AccessDenied",
    "NoSuchBucket",
    "NoSuchKey",
    "InvalidBucketName",
    "AccountProblem",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
}


class S3WriteResult:
    """Result of an S3 write operation with classification."""

    def __init__(self, success: bool, retriable: bool = False, error: str = ""):
        self.success = success
        self.retriable = retriable
        self.error = error

    @property
    def permanent_failure(self) -> bool:
        return not self.success and not self.retriable


def write_with_retry(
    bucket: str,
    key: str,
    body: bytes | str,
    max_retries: int = 2,
    base_delay: float = 1.0,
    region: str = "us-east-1",
) -> S3WriteResult:
    """Write to S3 with retry for transient failures.

    Classifies errors and only retries retriable ones.
    Returns a result object so callers can decide how to handle failures.

    Args:
        bucket: S3 bucket name.
        key: Object key.
        body: Content to write.
        max_retries: Max retry attempts for retriable errors.
        base_delay: Initial backoff delay in seconds.
        region: AWS region.

    Returns:
        S3WriteResult with success/failure classification.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")

    s3 = boto3.client("s3", region_name=region)

    for attempt in range(max_retries + 1):
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body)
            return S3WriteResult(success=True)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")

            if error_code in _PERMANENT_CODES:
                logger.error(
                    "S3 permanent failure (not retriable): %s — bucket=%s key=%s",
                    error_code, bucket, key,
                )
                return S3WriteResult(success=False, retriable=False, error=f"{error_code}: {e}")

            if error_code in _RETRIABLE_CODES and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "S3 retriable error %s (attempt %d/%d) — retrying in %.1fs",
                    error_code, attempt + 1, max_retries + 1, delay,
                )
                time.sleep(delay)
                continue

            # Unknown error code or exhausted retries
            return S3WriteResult(
                success=False,
                retriable=error_code in _RETRIABLE_CODES,
                error=f"{error_code}: {e}",
            )

        except (EndpointConnectionError, ReadTimeoutError) as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "S3 connection error (attempt %d/%d) — retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, e,
                )
                time.sleep(delay)
                continue

            return S3WriteResult(success=False, retriable=True, error=str(e))

        except Exception as e:
            return S3WriteResult(success=False, retriable=False, error=str(e))

    return S3WriteResult(success=False, retriable=True, error="Exhausted retries")
