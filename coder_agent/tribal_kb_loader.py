import json
import logging
import os
from functools import lru_cache
from typing import Dict, Any

logger = logging.getLogger(__name__)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIBAL_KB_DIR = os.path.join(BASE_DIR, "tribal_kb")


@lru_cache(maxsize=32)
def load_tribal_kb(project_type: str) -> Dict[str, Any]:
    """
    Load Tier-3 tribal knowledge JSON for a given project type.

    The file is expected at: app/utils/tribal_kb/{project_type}.json
    Returns an empty dict if not found or invalid, so the agent can gracefully
    fall back to generic generation.
    """
    if not project_type:
        return {}

    normalized = project_type.strip().lower()
    file_path = os.path.join(TRIBAL_KB_DIR, f"{normalized}.json")

    if not os.path.exists(file_path):
        logger.info("No tribal KB found for project_type=%s at %s", normalized, file_path)
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Tribal KB file for %s is not a JSON object", normalized)
            return {}
        return data
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load tribal KB for %s: %s", normalized, exc)
        return {}


