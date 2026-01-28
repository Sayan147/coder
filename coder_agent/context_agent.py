import logging
from typing import Any, Dict, Optional, List

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.crud.project_crud import project as project_crud
from app.crud.user_crud import user_crud
from app.utils.aws_utils import get_s3_file_content
from app.utils.deep_search import flatten_sections
from app.utils.memory_utils import get_messages
from .tribal_kb_loader import load_tribal_kb

logger = logging.getLogger(__name__)


def _load_project_kb_json(db: Session, project_id: int) -> Dict[str, Any]:
    """
    Load and minimally normalize the project knowledge base JSON from S3.
    Mirrors the logic in BRD generation, but kept small and read-only.
    """
    db_project = project_crud.get(db, project_id=project_id)
    if not db_project:
        raise ValueError(f"Project with ID {project_id} not found")

    kb_json_path = db_project.kb_json_path
    if not kb_json_path:
        raise ValueError(f"Project {project_id} does not have a knowledgebase JSON file")

    # kb_json_path expected like s3://bucket/key
    s3_key = (
        kb_json_path.replace("s3://", "")
        .replace(f"{settings.S3_BUCKET_NAME}/", "")
    )
    kb_json_bytes = get_s3_file_content(s3_key)
    import json

    project_data = json.loads(kb_json_bytes.decode("utf-8"))
    if not isinstance(project_data, dict):
        raise ValueError(f"KB JSON is not a dictionary, got {type(project_data)}")
    return project_data


def _summarize_history_for_coder(db: Session, session_id: Optional[str], use_sqlite: bool = False) -> str:
    """Summarize conversation history for coder agent.
    
    Args:
        db: Database session
        session_id: Optional session ID
        use_sqlite: If True, use memory_utils_sqlite instead of memory_utils
    """
    if not session_id:
        return ""
    try:
        if use_sqlite:
            from app.utils.memory_utils_sqlite import get_messages as get_messages_sqlite
            history = get_messages_sqlite(db, session_id, limit=10)
        else:
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
    project_id: int,
    user_id: int,
    project_type: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Consolidated context loader for the coder agent.

    Returns:
        {
          "project_data": ... full KB json dict ...,
          "code_sections": [... flat sections only for Code artifact, if present ...],
          "tribal_kb": {...},
          "conversation_history": "formatted history text"
        }
    """
    # Validate user exists (aligns with BRD route pattern)
    db_user = user_crud.get(db, user_id=user_id)
    if not db_user:
        raise ValueError(f"User with ID {user_id} not found")

    project_data = _load_project_kb_json(db, project_id)

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
    history_text = _summarize_history_for_coder(db, session_id, use_sqlite=False)

    return {
        "project_data": project_data,
        "code_sections": code_sections,
        "tribal_kb": tribal_kb,
        "conversation_history": history_text,
    }


def load_coder_context_sqlite(
    db: Session,
    project_data: Dict[str, Any],
    project_type: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SQLite version of context loader for the coder agent.
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
    history_text = _summarize_history_for_coder(db, session_id, use_sqlite=True)

    return {
        "project_data": project_data,
        "code_sections": code_sections,
        "tribal_kb": tribal_kb,
        "conversation_history": history_text,
    }


