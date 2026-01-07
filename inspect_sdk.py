
import inspect
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

print("ClaudeSDKClient members:")
for name, member in inspect.getmembers(ClaudeSDKClient):
    if not name.startswith("_"):
        print(f"- {name}")

print("\nClaudeAgentOptions fields:")
print(ClaudeAgentOptions.model_fields.keys())

# Check if we can pass a custom client
print("\nInit signature:")
print(inspect.signature(ClaudeSDKClient.__init__))
