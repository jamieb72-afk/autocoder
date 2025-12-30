"""
Projects Router
===============

API endpoints for project management.
"""

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import (
    ProjectCreate,
    ProjectSummary,
    ProjectDetail,
    ProjectPrompts,
    ProjectPromptsUpdate,
    ProjectStats,
)

# Lazy imports to avoid sys.path manipulation at module level
_imports_initialized = False
_GENERATIONS_DIR = None
_get_existing_projects = None
_check_spec_exists = None
_scaffold_project_prompts = None
_get_project_prompts_dir = None
_count_passing_tests = None


def _init_imports():
    """Lazy import of project-level modules."""
    global _imports_initialized, _GENERATIONS_DIR, _get_existing_projects
    global _check_spec_exists, _scaffold_project_prompts, _get_project_prompts_dir
    global _count_passing_tests

    if _imports_initialized:
        return

    import sys
    root = Path(__file__).parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from start import GENERATIONS_DIR, get_existing_projects, check_spec_exists
    from prompts import scaffold_project_prompts, get_project_prompts_dir
    from progress import count_passing_tests

    _GENERATIONS_DIR = GENERATIONS_DIR
    _get_existing_projects = get_existing_projects
    _check_spec_exists = check_spec_exists
    _scaffold_project_prompts = scaffold_project_prompts
    _get_project_prompts_dir = get_project_prompts_dir
    _count_passing_tests = count_passing_tests
    _imports_initialized = True


router = APIRouter(prefix="/api/projects", tags=["projects"])


def validate_project_name(name: str) -> str:
    """Validate and sanitize project name to prevent path traversal."""
    if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', name):
        raise HTTPException(
            status_code=400,
            detail="Invalid project name. Use only letters, numbers, hyphens, and underscores (1-50 chars)."
        )
    return name


def get_project_stats(project_dir: Path) -> ProjectStats:
    """Get statistics for a project."""
    _init_imports()
    passing, _, total = _count_passing_tests(project_dir)
    percentage = (passing / total * 100) if total > 0 else 0.0
    return ProjectStats(passing=passing, total=total, percentage=round(percentage, 1))


@router.get("", response_model=list[ProjectSummary])
async def list_projects():
    """List all projects in the generations directory."""
    _init_imports()
    projects = _get_existing_projects()
    result = []

    for name in projects:
        project_dir = _GENERATIONS_DIR / name
        has_spec = _check_spec_exists(project_dir)
        stats = get_project_stats(project_dir)

        result.append(ProjectSummary(
            name=name,
            has_spec=has_spec,
            stats=stats,
        ))

    return result


@router.post("", response_model=ProjectSummary)
async def create_project(project: ProjectCreate):
    """Create a new project with scaffolded prompts."""
    _init_imports()
    name = validate_project_name(project.name)

    project_dir = _GENERATIONS_DIR / name

    if project_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Project '{name}' already exists"
        )

    # Create project directory
    project_dir.mkdir(parents=True, exist_ok=True)

    # Scaffold prompts
    _scaffold_project_prompts(project_dir)

    return ProjectSummary(
        name=name,
        has_spec=False,  # Just created, no spec yet
        stats=ProjectStats(passing=0, total=0, percentage=0.0),
    )


@router.get("/{name}", response_model=ProjectDetail)
async def get_project(name: str):
    """Get detailed information about a project."""
    _init_imports()
    name = validate_project_name(name)
    project_dir = _GENERATIONS_DIR / name

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    has_spec = _check_spec_exists(project_dir)
    stats = get_project_stats(project_dir)
    prompts_dir = _get_project_prompts_dir(project_dir)

    return ProjectDetail(
        name=name,
        has_spec=has_spec,
        stats=stats,
        prompts_dir=str(prompts_dir),
    )


@router.delete("/{name}")
async def delete_project(name: str):
    """Delete a project and all its files."""
    _init_imports()
    name = validate_project_name(name)
    project_dir = _GENERATIONS_DIR / name

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    # Check if agent is running
    lock_file = project_dir / ".agent.lock"
    if lock_file.exists():
        raise HTTPException(
            status_code=409,
            detail="Cannot delete project while agent is running. Stop the agent first."
        )

    try:
        shutil.rmtree(project_dir)
        return {"success": True, "message": f"Project '{name}' deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {e}")


@router.get("/{name}/prompts", response_model=ProjectPrompts)
async def get_project_prompts(name: str):
    """Get the content of project prompt files."""
    _init_imports()
    name = validate_project_name(name)
    project_dir = _GENERATIONS_DIR / name

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    prompts_dir = _get_project_prompts_dir(project_dir)

    def read_file(filename: str) -> str:
        filepath = prompts_dir / filename
        if filepath.exists():
            try:
                return filepath.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""

    return ProjectPrompts(
        app_spec=read_file("app_spec.txt"),
        initializer_prompt=read_file("initializer_prompt.md"),
        coding_prompt=read_file("coding_prompt.md"),
    )


@router.put("/{name}/prompts")
async def update_project_prompts(name: str, prompts: ProjectPromptsUpdate):
    """Update project prompt files."""
    _init_imports()
    name = validate_project_name(name)
    project_dir = _GENERATIONS_DIR / name

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    prompts_dir = _get_project_prompts_dir(project_dir)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    def write_file(filename: str, content: str | None):
        if content is not None:
            filepath = prompts_dir / filename
            filepath.write_text(content, encoding="utf-8")

    write_file("app_spec.txt", prompts.app_spec)
    write_file("initializer_prompt.md", prompts.initializer_prompt)
    write_file("coding_prompt.md", prompts.coding_prompt)

    return {"success": True, "message": "Prompts updated"}


@router.get("/{name}/stats", response_model=ProjectStats)
async def get_project_stats_endpoint(name: str):
    """Get current progress statistics for a project."""
    _init_imports()
    name = validate_project_name(name)
    project_dir = _GENERATIONS_DIR / name

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    return get_project_stats(project_dir)
