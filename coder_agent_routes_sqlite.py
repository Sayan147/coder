"""
Coder Agent API routes with SQLite memory support.
SQLite version for development/testing.
Aligned with brd_generation_routes_sqlite.py patterns.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.configs.sqlite_config import SQLiteDatabase
from app.utils.memory_utils_sqlite import add_message, get_messages, ensure_session
from app.utils.coder_agent import (
    plan_code_generation,
    load_coder_context_sqlite,
    find_function_exemplars,
    generate_code_with_exemplars,
    validate_generated_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coder", tags=["Code Generation (Coder Agent - SQLite)"])


@router.post("/generate", response_model=dict, status_code=status.HTTP_201_CREATED)
async def generate_code(
    project_name: str = Form(..., description="Project name in project_json"),
    requirements: str = Form(..., description="Natural language requirements for the code to be generated"),
    project_type: str = Form(..., description="High-level project type (etl, regression, classification, fastapi, etc.)"),
    session_id: Optional[str] = Form(None, description="Optional session ID for conversation memory"),
    db: Session = Depends(SQLiteDatabase.get_db),
):
    """
    Main entrypoint for the Coder Agent (SQLite version).
    
    Flow (aligned with brd_generation_routes_sqlite.py):
      1) If session_id provided, retrieve conversation history for context
      2) Save user query to memory if session_id provided
      3) Load project KB from local filesystem (project_json directory)
      4) Navigator agent creates a simple generation plan
      5) Context agent loads KB, tribal KB, and conversation history
      6) Search agent finds function exemplars from the KB
      7) Code agent generates code and runs a light validation pass
      8) Save generated code to memory if session_id provided
      9) Return generated code + metadata
    """
    # Handle memory/session if provided
    conversation_history = None
    if session_id:
        ensure_session(db, session_id)
        # Save user query to memory
        user_message_content = f"[CODER Generation Request] ({project_type}) {requirements}"
        add_message(db, session_id, "user", user_message_content)
        
        # Retrieve conversation history for context
        history = get_messages(db, session_id, limit=10)
        if history:
            history_parts = []
            for msg in history[:-1]:  # Exclude the current message we just added
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_parts.append(f"{role.capitalize()}: {content}")
            conversation_history = "\n".join(history_parts)
            logger.info(f"Retrieved {len(history)} messages from session {session_id}")

    try:
        # Load project JSON from local filesystem (same pattern as BRD SQLite routes)
        from app.utils.knowbase_basic import find_project_by_name
        
        project = find_project_by_name(project_name, projects_directory="project_json")
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project '{project_name}' not found in project_json directory"
            )
        
        project_data = project.to_dict()

        # 4. Navigator: get a simple generation plan
        plan = plan_code_generation(requirements=requirements, project_type=project_type)

        # 5. Context: load KB, tribal KB, conversation history (SQLite version)
        context = load_coder_context_sqlite(
            db=db,
            project_data=project_data,
            project_type=project_type,
            session_id=session_id,
        )

        # 6. Search: find function exemplars based on main requirement
        exemplars = find_function_exemplars(
            requirement=requirements,
            code_sections=context["code_sections"],
            max_exemplars=3,
        )

        # 7. Code generation + validation
        raw_code = generate_code_with_exemplars(
            requirement=requirements,
            project_type=project_type,
            exemplars=exemplars,
            tribal_kb=context["tribal_kb"],
            conversation_history=context.get("conversation_history", ""),
        )

        is_valid, validation_details = validate_generated_code(
            code=raw_code,
            project_type=project_type,
            requirements=requirements,
        )

        # Save generated code to memory if session_id provided
        if session_id:
            assistant_message = (
                f"[CODER Generated Code] project='{project_name}' "
                f"type='{project_type}' (valid={is_valid})\n\n{raw_code}"
            )
            add_message(db, session_id, "assistant", assistant_message)
            logger.info(f"Saved coder generation to memory for session {session_id}")

        return {
            "success": True,
            "message": "Code generation completed" if is_valid else "Code generation completed with warnings",
            "project_name": project_name,
            "session_id": session_id,
            "plan": plan,
            "exemplars_used": exemplars,
            "code": raw_code,
            "validation": validation_details,
        }

    except HTTPException:
        # Let FastAPI handle already-formed HTTPExceptions
        raise
    except Exception as exc:
        logger.exception("Unexpected error in coder_agent /coder/generate (SQLite): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Coder agent failed: {exc}",
        )
