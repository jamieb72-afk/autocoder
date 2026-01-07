from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

# Adapter classes to match claude_agent_sdk types expected by agent.py

@dataclass
class TextBlock:
    text: str

@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str

@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False

@dataclass
class AssistantMessage:
    content: List[Union[TextBlock, ToolUseBlock]] = field(default_factory=list)

@dataclass
class UserMessage:
    content: List[ToolResultBlock] = field(default_factory=list)
