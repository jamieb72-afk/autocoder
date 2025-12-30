"""
Pydantic Schemas
================

Request/Response models for the API endpoints.
"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ============================================================================
# Project Schemas
# ============================================================================

class ProjectCreate(BaseModel):
    """Request schema for creating a new project."""
    name: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    spec_method: Literal["claude", "manual"] = "claude"


class ProjectStats(BaseModel):
    """Project statistics."""
    passing: int = 0
    total: int = 0
    percentage: float = 0.0


class ProjectSummary(BaseModel):
    """Summary of a project for list view."""
    name: str
    has_spec: bool
    stats: ProjectStats


class ProjectDetail(BaseModel):
    """Detailed project information."""
    name: str
    has_spec: bool
    stats: ProjectStats
    prompts_dir: str


class ProjectPrompts(BaseModel):
    """Project prompt files content."""
    app_spec: str = ""
    initializer_prompt: str = ""
    coding_prompt: str = ""


class ProjectPromptsUpdate(BaseModel):
    """Request schema for updating project prompts."""
    app_spec: str | None = None
    initializer_prompt: str | None = None
    coding_prompt: str | None = None


# ============================================================================
# Feature Schemas
# ============================================================================

class FeatureBase(BaseModel):
    """Base feature attributes."""
    category: str
    name: str
    description: str
    steps: list[str]


class FeatureCreate(FeatureBase):
    """Request schema for creating a new feature."""
    priority: int | None = None


class FeatureResponse(FeatureBase):
    """Response schema for a feature."""
    id: int
    priority: int
    passes: bool
    in_progress: bool

    class Config:
        from_attributes = True


class FeatureListResponse(BaseModel):
    """Response containing list of features organized by status."""
    pending: list[FeatureResponse]
    in_progress: list[FeatureResponse]
    done: list[FeatureResponse]


# ============================================================================
# Agent Schemas
# ============================================================================

class AgentStatus(BaseModel):
    """Current agent status."""
    status: Literal["stopped", "running", "paused", "crashed"]
    pid: int | None = None
    started_at: datetime | None = None


class AgentActionResponse(BaseModel):
    """Response for agent control actions."""
    success: bool
    status: str
    message: str = ""


# ============================================================================
# Setup Schemas
# ============================================================================

class SetupStatus(BaseModel):
    """System setup status."""
    claude_cli: bool
    credentials: bool
    node: bool
    npm: bool


# ============================================================================
# WebSocket Message Schemas
# ============================================================================

class WSProgressMessage(BaseModel):
    """WebSocket message for progress updates."""
    type: Literal["progress"] = "progress"
    passing: int
    total: int
    percentage: float


class WSFeatureUpdateMessage(BaseModel):
    """WebSocket message for feature status updates."""
    type: Literal["feature_update"] = "feature_update"
    feature_id: int
    passes: bool


class WSLogMessage(BaseModel):
    """WebSocket message for agent log output."""
    type: Literal["log"] = "log"
    line: str
    timestamp: datetime


class WSAgentStatusMessage(BaseModel):
    """WebSocket message for agent status changes."""
    type: Literal["agent_status"] = "agent_status"
    status: str
