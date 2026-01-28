import logging
from typing import Dict, List, Any

from app.utils.llm import call_llm

logger = logging.getLogger(__name__)


def plan_code_generation(requirements: str, project_type: str) -> Dict[str, Any]:
    """
    Navigator-style planner for code generation.

    Keeps this intentionally simple for v1: asks the LLM to decompose the
    requirement into a small set of components and KB search queries.
    """
    planning_prompt = (
        "You are a senior software architect helping another agent generate code.\n"
        "Given a user requirement and a project type, break the work into a small set "
        "of concrete code components and KB search hints.\n\n"
        "Return JSON with this shape ONLY:\n"
        "{\n"
        '  "components": [\n'
        '    {"name": "...", "description": "...", "priority": 1}\n'
        "  ],\n"
        '  "search_queries": ["...", "..."]\n'
        "}\n\n"
        f"PROJECT_TYPE: {project_type}\n"
        f"REQUIREMENTS:\n{requirements}\n"
    )

    try:
        raw = call_llm(planning_prompt) or ""
    except Exception as exc:
        logger.error("Navigator planning failed, falling back to default: %s", exc)
        raw = ""

    import json

    plan: Dict[str, Any] = {
        "components": [
            {
                "name": "main_module",
                "description": requirements,
                "priority": 1,
            }
        ],
        "search_queries": [requirements],
    }

    if not raw:
        return plan

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # Basic sanity checks
            if "components" in parsed and isinstance(parsed["components"], list):
                plan["components"] = parsed["components"]
            if "search_queries" in parsed and isinstance(parsed["search_queries"], list):
                plan["search_queries"] = parsed["search_queries"]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to parse navigator plan JSON, using fallback. Error: %s", exc)

    return plan


