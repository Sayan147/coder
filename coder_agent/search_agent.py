import logging
from typing import Any, Dict, List

from app.utils.deep_search import deep_search

logger = logging.getLogger(__name__)


def find_function_exemplars(
    requirement: str,
    code_sections: List[Dict[str, Any]],
    max_exemplars: int = 3,
) -> List[Dict[str, Any]]:
    """
    Use the existing deep_search utility over flattened code sections
    to pick 1..N exemplar sections that best match the requirement.

    For v1 we simply:
      - run a single deep_search call
      - use the chosen section as the primary exemplar
      - optionally add a couple of neighbors for extra context
    """
    if not code_sections:
        return []

    result = deep_search(requirement, code_sections)
    if not isinstance(result, dict):
        logger.warning("deep_search returned non-dict result, ignoring")
        return []

    idx = result.get("chosen_section_index")
    if idx is None or not isinstance(idx, int):
        logger.info("deep_search did not return a valid chosen_section_index")
        return []

    exemplars: List[Dict[str, Any]] = []

    def _build_exemplar(section_idx: int) -> Dict[str, Any]:
        entry = code_sections[section_idx]
        return {
            "index": section_idx,
            "artifact_name": entry.get("artifact_name"),
            "document_name": entry.get("document_name"),
            "section_name": entry.get("section_name"),
            "description": entry.get("description"),
        }

    # Primary exemplar
    exemplars.append(_build_exemplar(idx))

    # Add neighbors around the chosen index for some extra context
    for offset in (-1, 1, -2, 2):
        if len(exemplars) >= max_exemplars:
            break
        neighbor = idx + offset
        if 0 <= neighbor < len(code_sections):
            exemplars.append(_build_exemplar(neighbor))

    return exemplars


