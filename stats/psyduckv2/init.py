from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Dict
import config as AppConfig
from utils.http_api import APIClient

@asynccontextmanager
async def get_psyduck_client():
    """
    Builds an APIClient for Psyduckv2 using any combination of:
      - Custom header (PSYDUCKV2_API_HEADER: PSYDUCKV2_API_HEADER_SECRET)
      - Bearer token (PSYDUCKV2_API_SECRET_KEY) -> Authorization: Bearer <token>
    """
    if not AppConfig.PSYDUCKV2_URL:
        raise RuntimeError("PSYDUCKV2_URL is not configured")

    # Optional custom header (arbitrary header name/value)
    extra_headers: Dict[str, str] = {}
    if AppConfig.PSYDUCKV2_API_HEADER and AppConfig.PSYDUCKV2_API_HEADER_SECRET:
        extra_headers[AppConfig.PSYDUCKV2_API_HEADER] = AppConfig.PSYDUCKV2_API_HEADER_SECRET

    bearer = AppConfig.PSYDUCKV2_API_SECRET_KEY or None

    async with APIClient(
        AppConfig.PSYDUCKV2_URL,
        bearer=bearer,
        headers=extra_headers,
        timeout_s=30,
    ) as api:
        yield api
