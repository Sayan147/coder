import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.configs.config import Database
from app.core.settings import settings
from app.models.enums import ExecutionStatusEnum
from app.utils.memory_utils import add_message
from app.utils.coder_agent import (
    plan_code_generation,
    load_coder_context,
    find_function_exemplars,
    generate_code_with_exemplars,
    validate_generated_code,
)

from app.crud.agent_definition_crud import agent_definition
from app.crud.agent_execution_crud import agent_execution
from app.crud.user_crud import user_crud
from app.crud.project_crud import project as project_crud
from app.utils.session_utils import generate_execution_session_id

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/coder", tags=["Code Generation (Coder Agent)"])


@router.post("/generate", response_model=dict, status_code=status.HTTP_201_CREATED)
async def generate_code(
    project_id: int = Query(..., description="Project ID whose KB will be used as exemplars"),
    user_id: int = Query(..., description="User ID triggering the code generation"),
    requirements: str = Form(..., description="Natural language requirements for the code to be generated"),
    project_type: str = Form(..., description="High-level project type (etl, regression, classification, fastapi, etc.)"),
    session_id: Optional[str] = Form(None, description="Optional session ID for conversation memory"),
    db: Session = Depends(Database.get_db),
):
    """
    Main entrypoint for the Coder Agent.

    Flow (aligned with existing BRD patterns, but simplified for code generation):
      1) Resolve / create Coder agent definition
      2) Create AgentExecution for traceability
      3) Derive or use session_id and log the user request into memory
      4) Navigator agent creates a simple generation plan
      5) Context agent loads KB, tribal KB, and conversation history
      6) Search agent finds function exemplars from the KB
      7) Code agent generates code and runs a light validation pass
      8) Persist execution status and return generated code + metadata
    """
    # 0. Basic entity checks
    db_user = user_crud.get(db, user_id=user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    db_project = project_crud.get(db, project_id=project_id)
    if not db_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    user_session_id = db_user.session_id

    # 1. Get or create Coder agent definition
    coder_agent = agent_definition.get_by_name(db, agent_name="CODER")
    if not coder_agent:
        coder_agent = agent_definition.create(
            db,
            obj_in={
                "agent_name": "CODER",
                "agent_category": "DEVELOPER",
                "description": "Coder agent for code generation using project KB and tribal knowledge",
                "created_by_user_id": user_id,
            },
        )
        logger.info("Created CODER agent definition with ID: %s", coder_agent.agent_def_id)

    # 2. Create AgentExecution record
    execution_data = {
        "project_id": project_id,
        "agent_def_id": coder_agent.agent_def_id,
        "triggered_by_user_id": user_id,
        "user_prompt": requirements,
        "status": ExecutionStatusEnum.STARTED,
        "chat_trace_name": f"coder_generation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    }
    execution = agent_execution.create(db, obj_in=execution_data)
    execution_id = execution.execution_id
    logger.info("Created CODER AgentExecution with ID: %s for project %s", execution_id, project_id)

    # 3. Derive session_id if not supplied
    if not session_id:
        session_id = generate_execution_session_id(user_session_id, project_id, execution_id)
        logger.info("Generated hierarchical session_id for coder agent: %s", session_id)

    # Log the raw user request into memory (guardrails/memory integration)
    try:
        user_message_content = f"[CODER Generation Request] ({project_type}) {requirements}"
        add_message(db, session_id, "user", user_message_content)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to write initial coder message to memory: %s", exc)

    try:
        # 4. Navigator: get a simple generation plan
        plan = plan_code_generation(requirements=requirements, project_type=project_type)

        # 5. Context: load KB, tribal KB, conversation history
        context = load_coder_context(
            db=db,
            project_id=project_id,
            user_id=user_id,
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

        # Log assistant response into memory
        try:
            assistant_message = (
                f"[CODER Generated Code] project='{db_project.project_name}' "
                f"type='{project_type}' (valid={is_valid})\n\n{raw_code}"
            )
            add_message(db, session_id, "assistant", assistant_message)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to write coder response to memory: %s", exc)

        # 8. Finalize AgentExecution
        agent_execution.update(
            db,
            db_obj=execution,
            obj_in={
                "status": ExecutionStatusEnum.COMPLETED if is_valid else ExecutionStatusEnum.AWAITING_FEEDBACK,
                "agent_response_text": raw_code,
                "completed_at": datetime.now(),
            },
        )

        return {
            "success": True,
            "message": "Code generation completed" if is_valid else "Code generation completed with warnings",
            "project_id": project_id,
            "project_name": db_project.project_name,
            "execution_id": execution_id,
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
        logger.exception("Unexpected error in coder_agent /coder/generate: %s", exc)
        agent_execution.update(
            db,
            db_obj=execution,
            obj_in={
                "status": ExecutionStatusEnum.FAILED,
                "agent_response_text": str(exc),
                "completed_at": datetime.now(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Coder agent failed: {exc}",
        )


