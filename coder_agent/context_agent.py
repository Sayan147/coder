"""
Context Agent for Coder Agent - SQLite version only.
Loads project KB, tribal KB, and conversation history.
"""

import logging
from typing import Any, Dict, Optional, List

from sqlalchemy.orm import Session

from app.utils.deep_search import flatten_sections
from app.utils.memory_utils_sqlite import get_messages
from .tribal_kb_loader import load_tribal_kb

logger = logging.getLogger(__name__)


def _summarize_history_for_coder(db: Session, session_id: Optional[str]) -> str:
    """
    Summarize conversation history for coder agent using SQLite memory utils.
    
    Args:
        db: SQLite database session
        session_id: Optional session ID
        
    Returns:
        Formatted conversation history string
    """
    if not session_id:
        return ""
    try:
        history = get_messages(db, session_id, limit=10)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load history for session %s: %s", session_id, exc)
        return ""

    parts: List[str] = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"{role.capitalize()}: {content}")
    return "\n".join(parts)


def load_coder_context(
    db: Session,
    project_data: Dict[str, Any],
    project_type: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Consolidated context loader for the coder agent (SQLite version).
    Takes project_data directly (already loaded from local filesystem).
    
    Args:
        db: SQLite database session
        project_data: Project KB JSON dict (already loaded from project_json directory)
        project_type: Project type (etl, regression, etc.)
        session_id: Optional session ID for conversation history
        
    Returns:
        {
          "project_data": ... full KB json dict ...,
          "code_sections": [... flat sections only for Code artifact, if present ...],
          "tribal_kb": {...},
          "conversation_history": "formatted history text"
        }
    """
    # Prefer only Code artifact sections as exemplars, fall back to all if not present
    all_sections = flatten_sections(project_data, tier=None)
    code_sections: List[Dict[str, Any]] = []
    for entry in all_sections:
        artifact_name = str(entry.get("artifact_name", "")).lower()
        if artifact_name == "code":
            code_sections.append(entry)
    if not code_sections:
        code_sections = all_sections

    tribal_kb = load_tribal_kb(project_type)
    history_text = _summarize_history_for_coder(db, session_id)

    return {
        "project_data": project_data,
        "code_sections": code_sections,
        "tribal_kb": tribal_kb,
        "conversation_history": history_text,
    }
