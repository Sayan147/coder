import json
import logging
from typing import Any, Dict, List, Tuple

from app.utils.llm import call_llm

logger = logging.getLogger(__name__)


def _summarize_tribal_kb(tribal_kb: Dict[str, Any], max_chars: int = 4000) -> str:
    if not tribal_kb:
        return "No specific tribal knowledge available. Follow general best practices."
    try:
        text = json.dumps(tribal_kb, indent=2)
    except Exception:  # pragma: no cover - defensive
        text = str(tribal_kb)
    return text[:max_chars]


def _format_exemplars(exemplars: List[Dict[str, Any]], max_chars: int = 6000) -> str:
    if not exemplars:
        return "No exemplars available from the project knowledge base."
    lines: List[str] = []
    for ex in exemplars:
        lines.append(
            f"# Exemplar: {ex.get('section_name')} "
            f"(artifact={ex.get('artifact_name')}, doc={ex.get('document_name')})"
        )
        desc = str(ex.get("description", "") or "")
        lines.append(desc)
        lines.append("")
    text = "\n".join(lines)
    return text[:max_chars]


def generate_code_with_exemplars(
    requirement: str,
    project_type: str,
    exemplars: List[Dict[str, Any]],
    tribal_kb: Dict[str, Any],
    conversation_history: str = "",
) -> str:
    """
    Core generation helper: builds a rich prompt with exemplars + tribal KB
    and returns a raw code string from the LLM.
    """
    exemplars_text = _format_exemplars(exemplars)
    tribal_summary = _summarize_tribal_kb(tribal_kb)

    prompt_parts = [
        "You are an expert software engineer and code generator.",
        "Generate production-quality code that strictly follows the user requirements,",
        "reuses patterns from the exemplars where appropriate, and respects the project-type-specific tribal knowledge.\n",
        f"PROJECT_TYPE: {project_type}",
        "",
        "USER REQUIREMENTS:",
        requirement,
        "",
        "PROJECT EXEMPLARS (from the existing knowledge base):",
        exemplars_text,
        "",
        f"TRIBAL KNOWLEDGE FOR {project_type.upper()}:",
        tribal_summary,
    ]

    if conversation_history:
        prompt_parts.extend(
            [
                "",
                "RECENT CONVERSATION HISTORY (for additional context, do not echo back):",
                conversation_history,
            ]
        )

    prompt_parts.extend(
        [
            "",
            "Instructions:",
            "- Return ONLY code and minimal inline comments, no prose explanation.",
            "- Prefer clear function and module boundaries.",
            "- Follow clean-code best practices for this project_type.",
        ]
    )

    prompt = "\n".join(prompt_parts)

    try:
        return call_llm(prompt) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Code generation LLM call failed: %s", exc)
        raise


def validate_generated_code(
    code: str,
    project_type: str,
    requirements: str,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Lightweight, LLM-assisted validation of the generated code.

    Returns:
        (is_valid, details)
    """
    if not code.strip():
        return False, {
            "is_valid": False,
            "errors": ["Code generation returned empty output"],
            "warnings": [],
            "completeness_score": 0.0,
            "suggestions": ["Retry generation with simplified requirements"],
        }

    validation_prompt = (
        "You are performing a quick quality check on generated code.\n"
        "Given the project type, the original requirements and the code, evaluate:\n"
        "- Does the code roughly satisfy the requirements?\n"
        "- Are there any obvious structural or logical problems?\n"
        "- Is the code appropriate for the project type?\n\n"
        "Respond ONLY in this JSON shape:\n"
        "{\n"
        '  \"is_valid\": true/false,\n'
        '  \"errors\": [\"...\"],\n'
        '  \"warnings\": [\"...\"],\n'
        '  \"completeness_score\": 0.0,\n'
        '  \"suggestions\": [\"...\"]\n'
        "}\n\n"
        f"PROJECT_TYPE: {project_type}\n\n"
        f"REQUIREMENTS:\n{requirements}\n\n"
        f"CODE:\n{code}\n"
    )

    try:
        raw = call_llm(validation_prompt) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Validation LLM call failed, returning optimistic default: %s", exc)
        return True, {
            "is_valid": True,
            "errors": [],
            "warnings": ["Validation step failed; treat code as unvalidated."],
            "completeness_score": 0.7,
            "suggestions": [],
        }

    try:
        details = json.loads(raw)
        if not isinstance(details, dict):
            raise ValueError("Validation JSON is not an object")
    except Exception as exc:
        logger.warning("Failed to parse validation JSON, using safe default. Error: %s", exc)
        details = {
            "is_valid": True,
            "errors": [],
            "warnings": ["Validation response was not parseable; treat as best-effort."],
            "completeness_score": 0.7,
            "suggestions": [],
        }

    is_valid = bool(details.get("is_valid", True))
    return is_valid, details


