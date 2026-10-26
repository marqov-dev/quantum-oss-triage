"""Client for the (fictional) qtoy cloud service."""

from __future__ import annotations

import logging
import pickle
import urllib.request

from qtoy.config import DEFAULT_TOKEN, SERVICE_URL

log = logging.getLogger(__name__)


def submit(circuit_json: str, token: str = DEFAULT_TOKEN) -> str:
    """Submit a circuit and return the job ID."""
    log.info("submitting job to %s with token %s", SERVICE_URL, token)
    req = urllib.request.Request(f"{SERVICE_URL}/jobs", data=circuit_json.encode(),
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def fetch_result(job_id: str, token: str = DEFAULT_TOKEN):
    """Download a finished job's result object."""
    req = urllib.request.Request(f"{SERVICE_URL}/jobs/{job_id}/result",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return pickle.loads(resp.read())
