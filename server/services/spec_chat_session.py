"""
Spec Creation Chat Session
==========================

Manages interactive spec creation conversation with Claude.
Uses the create-spec.md skill to guide users through app spec creation.
"""

import asyncio
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

logger = logging.getLogger(__name__)

# Root directory of the project
ROOT_DIR = Path(__file__).parent.parent.parent


class SpecChatSession:
    """
    Manages a spec creation conversation for one project.

    Uses the create-spec skill to guide users through:
    - Phase 1: Project Overview (name, description, audience)
    - Phase 2: Involvement Level (Quick vs Detailed mode)
    - Phase 3: Technology Preferences
    - Phase 4: Features (main exploration phase)
    - Phase 5: Technical Details (derived or discussed)
    - Phase 6-7: Success Criteria & Approval
    """

    def __init__(self, project_name: str):
        """
        Initialize the session.

        Args:
            project_name: Name of the project being created
        """
        self.project_name = project_name
        self.project_dir = ROOT_DIR / "generations" / project_name
        self.client: Optional[ClaudeSDKClient] = None
        self.messages: list[dict] = []
        self.complete: bool = False
        self.created_at = datetime.now()
        self._conversation_id: Optional[str] = None
        self._client_entered: bool = False  # Track if context manager is active

    async def close(self) -> None:
        """Clean up resources and close the Claude client."""
        if self.client and self._client_entered:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Claude client: {e}")
            finally:
                self._client_entered = False
                self.client = None

    async def start(self) -> AsyncGenerator[dict, None]:
        """
        Initialize session and get initial greeting from Claude.

        Yields message chunks as they stream in.
        """
        # Load the create-spec skill
        skill_path = ROOT_DIR / ".claude" / "commands" / "create-spec.md"

        if not skill_path.exists():
            yield {
                "type": "error",
                "content": f"Spec creation skill not found at {skill_path}"
            }
            return

        try:
            skill_content = skill_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skill_content = skill_path.read_text(encoding="utf-8", errors="replace")

        # Replace $ARGUMENTS with the project path (use forward slashes for consistency)
        project_path = f"generations/{self.project_name}"
        system_prompt = skill_content.replace("$ARGUMENTS", project_path)

        # Create Claude SDK client with limited tools for spec creation
        try:
            self.client = ClaudeSDKClient(
                options=ClaudeAgentOptions(
                    model="claude-sonnet-4-20250514",
                    system_prompt=system_prompt,
                    allowed_tools=[
                        "Read",
                        "Write",
                        "AskUserQuestion",
                    ],
                    max_turns=100,
                    cwd=str(ROOT_DIR.resolve()),
                )
            )
            # Enter the async context and track it
            await self.client.__aenter__()
            self._client_entered = True
        except Exception as e:
            logger.exception("Failed to create Claude client")
            yield {
                "type": "error",
                "content": f"Failed to initialize Claude: {str(e)}"
            }
            return

        # Start the conversation - Claude will send the Phase 1 greeting
        try:
            async for chunk in self._query_claude("Begin the spec creation process."):
                yield chunk
            # Signal that the response is complete (for UI to hide loading indicator)
            yield {"type": "response_done"}
        except Exception as e:
            logger.exception("Failed to start spec chat")
            yield {
                "type": "error",
                "content": f"Failed to start conversation: {str(e)}"
            }

    async def send_message(self, user_message: str) -> AsyncGenerator[dict, None]:
        """
        Send user message and stream Claude's response.

        Args:
            user_message: The user's response

        Yields:
            Message chunks of various types:
            - {"type": "text", "content": str}
            - {"type": "question", "questions": list}
            - {"type": "spec_complete", "path": str}
            - {"type": "error", "content": str}
        """
        if not self.client:
            yield {
                "type": "error",
                "content": "Session not initialized. Call start() first."
            }
            return

        # Store the user message
        self.messages.append({
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now().isoformat()
        })

        try:
            async for chunk in self._query_claude(user_message):
                yield chunk
            # Signal that the response is complete (for UI to hide loading indicator)
            yield {"type": "response_done"}
        except Exception as e:
            logger.exception("Error during Claude query")
            yield {
                "type": "error",
                "content": f"Error: {str(e)}"
            }

    async def _query_claude(self, message: str) -> AsyncGenerator[dict, None]:
        """
        Internal method to query Claude and stream responses.

        Handles tool calls (AskUserQuestion, Write) and text responses.
        """
        if not self.client:
            return

        # Send the message to Claude using the SDK's query method
        await self.client.query(message)

        current_text = ""

        # Stream the response using receive_response
        async for msg in self.client.receive_response():
            msg_type = type(msg).__name__

            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                # Process content blocks in the assistant message
                for block in msg.content:
                    block_type = type(block).__name__

                    if block_type == "TextBlock" and hasattr(block, "text"):
                        # Accumulate text and yield it
                        text = block.text
                        if text:
                            current_text += text
                            yield {"type": "text", "content": text}

                            # Store in message history
                            self.messages.append({
                                "role": "assistant",
                                "content": text,
                                "timestamp": datetime.now().isoformat()
                            })

                    elif block_type == "ToolUseBlock" and hasattr(block, "name"):
                        tool_name = block.name
                        tool_input = getattr(block, "input", {})
                        tool_id = getattr(block, "id", "")

                        if tool_name == "AskUserQuestion":
                            # Convert AskUserQuestion to structured UI
                            questions = tool_input.get("questions", [])
                            yield {
                                "type": "question",
                                "questions": questions,
                                "tool_id": tool_id
                            }
                            # The SDK handles tool results internally

                        elif tool_name == "Write":
                            # File being written - the SDK handles this
                            file_path = tool_input.get("file_path", "")

                            # Check if this is the app_spec.txt file
                            if "app_spec.txt" in str(file_path):
                                self.complete = True
                                yield {
                                    "type": "spec_complete",
                                    "path": str(file_path)
                                }

                            elif "initializer_prompt.md" in str(file_path):
                                yield {
                                    "type": "file_written",
                                    "path": str(file_path)
                                }

            elif msg_type == "UserMessage" and hasattr(msg, "content"):
                # Tool results - the SDK handles these automatically
                # We just watch for any errors
                for block in msg.content:
                    block_type = type(block).__name__
                    if block_type == "ToolResultBlock":
                        is_error = getattr(block, "is_error", False)
                        if is_error:
                            content = getattr(block, "content", "Unknown error")
                            logger.warning(f"Tool error: {content}")

    def is_complete(self) -> bool:
        """Check if spec creation is complete."""
        return self.complete

    def get_messages(self) -> list[dict]:
        """Get all messages in the conversation."""
        return self.messages.copy()


# Session registry with thread safety
_sessions: dict[str, SpecChatSession] = {}
_sessions_lock = threading.Lock()


def get_session(project_name: str) -> Optional[SpecChatSession]:
    """Get an existing session for a project."""
    with _sessions_lock:
        return _sessions.get(project_name)


async def create_session(project_name: str) -> SpecChatSession:
    """Create a new session for a project, closing any existing one."""
    old_session: Optional[SpecChatSession] = None

    with _sessions_lock:
        # Get existing session to close later (outside the lock)
        old_session = _sessions.pop(project_name, None)
        session = SpecChatSession(project_name)
        _sessions[project_name] = session

    # Close old session outside the lock to avoid blocking
    if old_session:
        try:
            await old_session.close()
        except Exception as e:
            logger.warning(f"Error closing old session for {project_name}: {e}")

    return session


async def remove_session(project_name: str) -> None:
    """Remove and close a session."""
    session: Optional[SpecChatSession] = None

    with _sessions_lock:
        session = _sessions.pop(project_name, None)

    # Close session outside the lock
    if session:
        try:
            await session.close()
        except Exception as e:
            logger.warning(f"Error closing session for {project_name}: {e}")


def list_sessions() -> list[str]:
    """List all active session project names."""
    with _sessions_lock:
        return list(_sessions.keys())


async def cleanup_all_sessions() -> None:
    """Close all active sessions. Called on server shutdown."""
    sessions_to_close: list[SpecChatSession] = []

    with _sessions_lock:
        sessions_to_close = list(_sessions.values())
        _sessions.clear()

    for session in sessions_to_close:
        try:
            await session.close()
        except Exception as e:
            logger.warning(f"Error closing session {session.project_name}: {e}")
