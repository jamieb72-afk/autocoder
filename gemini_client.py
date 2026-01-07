import os
import sys
import asyncio
import glob
import subprocess
import json
import re
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any, Union

# Ensure we can import from local modules
sys.path.append(str(Path(__file__).parent))

try:
    import google.generativeai as genai
    from google.generativeai.types import content_types
    from google.protobuf import struct_pb2
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

from gemini_types import (
    AssistantMessage, UserMessage, TextBlock, ToolUseBlock, ToolResultBlock
)
from security import bash_security_hook

# Import feature tools
# We need to set PROJECT_DIR for feature_mcp to work correctly if not set
if "PROJECT_DIR" not in os.environ:
    os.environ["PROJECT_DIR"] = os.getcwd()

try:
    from mcp_server import feature_mcp
except ImportError:
    feature_mcp = None


class GeminiClient:
    def __init__(self, project_dir: Path, model_name: str, yolo_mode: bool = False):
        if not HAS_GEMINI:
            raise ImportError("google-generativeai package is missing. Please install it.")
        
        self.project_dir = project_dir
        self.model_name = model_name
        
        # Normalize model name (remove 'gemini-' prefix if needed or map to actual Gemini model names)
        # The UI sends e.g. "gemini-1.5-pro-latest"
        # genai expects "models/gemini-1.5-pro-latest" or just "gemini-1.5-pro-latest"
        self.genai_model_name = model_name
        
        self.api_key = os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            print("[Warning] GOOGLE_API_KEY not found in environment.")
        
        genai.configure(api_key=self.api_key)
        
        self.history = []
        self.yolo_mode = yolo_mode
        
        # Define tools
        self.tools = self._get_tools()
        self.function_map = self._get_function_map()
        
        # Initialize model
        self.model = genai.GenerativeModel(
            model_name=self.genai_model_name,
            tools=self.tools,
            system_instruction="You are an expert full-stack developer building a production-quality web application. You are working in a persistent environment. You can read, write, and edit files, run bash commands, and manage project features."
        )
        self.chat = self.model.start_chat(history=self.history)
        self.pending_message = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def _get_tools(self):
        """Define tools for Gemini."""
        return [
            self._tool_read,
            self._tool_write,
            self._tool_edit,
            self._tool_bash,
            self._tool_glob,
            self._tool_grep,
            # Feature tools
            feature_mcp.feature_get_stats,
            feature_mcp.feature_get_next,
            feature_mcp.feature_get_for_regression,
            feature_mcp.feature_mark_passing,
            feature_mcp.feature_skip,
            feature_mcp.feature_mark_in_progress,
            feature_mcp.feature_create_bulk,
        ]

    def _get_function_map(self):
        """Map function names to callables."""
        mapping = {
            "Read": self._execute_read,
            "Write": self._execute_write,
            "Edit": self._execute_edit,
            "Bash": self._execute_bash,
            "Glob": self._execute_glob,
            "Grep": self._execute_grep,
        }
        
        # Add feature tools
        if feature_mcp:
            mapping.update({
                "feature_get_stats": feature_mcp.feature_get_stats,
                "feature_get_next": feature_mcp.feature_get_next,
                "feature_get_for_regression": feature_mcp.feature_get_for_regression,
                "feature_mark_passing": feature_mcp.feature_mark_passing,
                "feature_skip": feature_mcp.feature_skip,
                "feature_mark_in_progress": feature_mcp.feature_mark_in_progress,
                "feature_create_bulk": feature_mcp.feature_create_bulk,
            })
            
        return mapping

    # --- Tool Definitions (for Gemini) ---
    
    def _tool_read(self, paths: List[str]):
        """Read the content of one or more files."""
        pass

    def _tool_write(self, path: str, content: str):
        """Write content to a file (overwrites)."""
        pass

    def _tool_edit(self, path: str, old_string: str, new_string: str):
        """Replace text in a file. old_string must match exactly."""
        pass

    def _tool_bash(self, command: str):
        """Run a bash command."""
        pass

    def _tool_glob(self, pattern: str):
        """Find files matching a glob pattern."""
        pass

    def _tool_grep(self, pattern: str, path: str):
        """Search for a regex pattern in a path."""
        pass

    # --- Tool Execution Implementations ---

    def _execute_read(self, paths: List[str]) -> str:
        results = []
        for p in paths:
            try:
                full_path = self.project_dir / p
                if full_path.exists() and full_path.is_file():
                    with open(full_path, "r", encoding="utf-8") as f:
                        results.append(f"---\n{p} ---\n{f.read()}\n")
                else:
                    results.append(f"---\n{p} ---\n[File not found]\n")
            except Exception as e:
                results.append(f"---\n{p} ---\n[Error: {e}]\n")
        return "\n".join(results)

    def _execute_write(self, path: str, content: str) -> str:
        try:
            full_path = self.project_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing to {path}: {e}"

    def _execute_edit(self, path: str, old_string: str, new_string: str) -> str:
        try:
            full_path = self.project_dir / path
            if not full_path.exists():
                return f"Error: File {path} not found"
            
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if old_string not in content:
                # Try sloppy matching if exact match fails (simple whitespace normalization)
                if old_string.strip() in content:
                     content = content.replace(old_string.strip(), new_string)
                else:
                    return f"Error: old_string not found in {path}. Please check whitespace."
            else:
                content = content.replace(old_string, new_string)
                
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing {path}: {e}"

    async def _execute_bash(self, command: str) -> str:
        # Check security
        input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
        security_result = await bash_security_hook(input_data)
        if security_result.get("decision") == "block":
            return f"Security Blocked: {security_result.get('reason')}"
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_dir)
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode() + stderr.decode()
            return output if output.strip() else "[Command finished with no output]"
        except Exception as e:
            return f"Error executing command: {e}"

    def _execute_glob(self, pattern: str) -> str:
        try:
            # security check? minimal
            files = glob.glob(str(self.project_dir / pattern), recursive=True)
            rel_files = [str(Path(f).relative_to(self.project_dir)) for f in files if Path(f).is_file()]
            return "\n".join(rel_files) if rel_files else "[No files found]"
        except Exception as e:
            return f"Error globbing: {e}"

    def _execute_grep(self, pattern: str, path: str) -> str:
        try:
            cmd = ["grep", "-r", pattern, path]
            result = subprocess.run(
                cmd, 
                cwd=str(self.project_dir),
                capture_output=True,
                text=True
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Error grep: {e}"

    # --- Agent Interface ---

    async def query(self, message: str):
        """Send a message to the agent."""
        self.pending_message = message

    async def receive_response(self) -> AsyncGenerator[Union[AssistantMessage, UserMessage], None]:
        """Execute the agent loop: Send -> (Receive -> Tool -> Send)* -> Final Response"""
        
        if not self.pending_message:
            return

        current_message = self.pending_message
        self.pending_message = None
        
        # Max turns to prevent infinite loops
        max_turns = 20
        turn = 0
        
        while turn < max_turns:
            turn += 1
            
            # Send message to Gemini
            try:
                # We need to send the message. 
                # If it's the first turn, it's the user prompt.
                # If it's subsequent turns, it's tool outputs.
                
                response = await self.chat.send_message_async(current_message)
                
                # Construct AssistantMessage from response
                assistant_msg = AssistantMessage()
                
                # Check for function calls
                function_calls = []
                text_parts = []
                
                for part in response.parts:
                    if part.text:
                        text_parts.append(part.text)
                        assistant_msg.content.append(TextBlock(text=part.text))
                    
                    if part.function_call:
                        fc = part.function_call
                        # Convert arguments to dict
                        args = dict(fc.args)
                        
                        tool_use_id = f"call_{turn}_{len(function_calls)}"
                        tool_block = ToolUseBlock(
                            name=fc.name,
                            input=args,
                            id=tool_use_id
                        )
                        assistant_msg.content.append(tool_block)
                        function_calls.append((fc.name, args, tool_use_id))
                
                # Yield the assistant's thought/action
                yield assistant_msg
                
                # If no function calls, we are done
                if not function_calls:
                    break
                
                # Execute tools
                user_msg = UserMessage()
                tool_outputs = []
                
                for name, args, tool_id in function_calls:
                    result = ""
                    is_error = False
                    
                    if name in self.function_map:
                        func = self.function_map[name]
                        try:
                            # Handle async functions
                            if asyncio.iscoroutinefunction(func):
                                # Special case for Bash which is async
                                if name == "Bash":
                                    result = await self._execute_bash(args.get("command", ""))
                                else:
                                    # Feature tools might be async? No, mcp tools in feature_mcp seem sync
                                    # But let's check inspection or just try/except
                                    result = func(**args)
                                    if asyncio.iscoroutine(result):
                                        result = await result
                            else:
                                # Feature tools return JSON string directly
                                result = func(**args)
                        except Exception as e:
                            result = f"Error executing {name}: {str(e)}"
                            is_error = True
                    else:
                        result = f"Error: Unknown tool {name}"
                        is_error = True
                        
                    user_msg.content.append(ToolResultBlock(
                        tool_use_id=tool_id,
                        content=str(result),
                        is_error=is_error
                    ))
                    
                    # Prepare response for Gemini (FunctionResponse)
                    # Gemini expects a specific format for function responses
                    tool_outputs.append(
                        content_types.Part(
                            function_response=content_types.FunctionResponse(
                                name=name,
                                response={"result": result}
                            )
                        )
                    )

                yield user_msg
                
                # Set next message to be the tool outputs
                # Gemini chat.send_message handles the list of parts
                current_message = tool_outputs
                
            except Exception as e:
                # If critical error, yield it (maybe as text?) and break
                print(f"Gemini Error: {e}")
                err_msg = AssistantMessage(content=[TextBlock(text=f"Error: {str(e)}")])
                yield err_msg
                break
