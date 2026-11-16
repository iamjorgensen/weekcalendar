"""Shared helpers for the AWS Lambda functions (stdlib + boto3 only)."""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# SSM parameter names under PARAM_PREFIX. They map 1:1 to the environment
# variables data_provider.py reads at import time.
DATA_PARAM_NAMES = [
    "API_KEY_GOOGLE",
    "CALENDAR_ID",
    "HOLIDAYS_CALENDAR_ID",
    "MOVAR_API_TOKEN",
    "MOVAR_BASE",
    "KOMMUNENR",
    "MOVAR_GATENAVN",
    "MOVAR_HUSNR",
    "LAT",
    "LON",
    "OPENAI_API_KEY",
]
FRAME_TOKEN_PARAM = "FRAME_TOKEN"

_clients = {}


def client(service, **kwargs):
    """Cached boto3 client (one per service/config per container)."""
    key = (service, tuple(sorted((k, repr(v)) for k, v in kwargs.items())))
    if key not in _clients:
        _clients[key] = boto3.client(service, **kwargs)
    return _clients[key]


def reset_clients():
    """For tests: drop cached clients so new mocks take effect."""
    _clients.clear()


def param_prefix():
    prefix = os.environ.get("PARAM_PREFIX", "/weekcalendar/")
    return prefix if prefix.endswith("/") else prefix + "/"


def get_parameters(names):
    """
    Fetch SSM parameters (decrypted). Returns ({name: value}, [missing names]).
    Missing parameters and API errors are logged (names only, never values)
    and do not raise.
    """
    prefix = param_prefix()
    found, missing = {}, []
    ssm = client("ssm")
    names = list(names)
    for i in range(0, len(names), 10):  # GetParameters takes at most 10 names
        chunk = names[i:i + 10]
        try:
            resp = ssm.get_parameters(Names=[prefix + n for n in chunk], WithDecryption=True)
        except (ClientError, BotoCoreError) as e:
            logger.error("SSM get_parameters failed for %s: %s", chunk, e)
            missing.extend(chunk)
            continue
        for p in resp.get("Parameters", []):
            found[p["Name"][len(prefix):]] = p["Value"]
        for full in resp.get("InvalidParameters", []):
            missing.append(full[len(prefix):] if full.startswith(prefix) else full)
    return found, missing


def load_params_into_env(names=DATA_PARAM_NAMES):
    """Copy SSM parameters into os.environ. Returns the list of missing names."""
    found, missing = get_parameters(names)
    for name, value in found.items():
        os.environ[name] = value
    if missing:
        logger.warning("SSM parameters not set (optional ones may be fine): %s", ", ".join(sorted(missing)))
    logger.info("Loaded %d SSM parameters into env: %s", len(found), ", ".join(sorted(found)))
    return missing
