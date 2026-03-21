📘 AI Agent System Requirements (Production-Ready)
1. Purpose and Scope
Develop a lightweight, atomic, self-contained AI Agent that:
Operates using a ReAct-style loop (reason → act → observe)
Communicates strictly via a JSON-based protocol
Can spawn child agents, forming a controlled hierarchical tree
Interacts with the external environment only through predefined commands
Is deterministic, bounded, and resilient to LLM errors
Each agent instance is:
Single-role
Independently configured
Fully isolated in execution context
2. Technology Requirements
Python 3.11+
Dependencies:
openai
PyYAML
Standard library only (os, subprocess, json, typing, etc.)
Environment variable:
OPENAI_API_KEY (required)
No external frameworks allowed (e.g., LangChain, CrewAI, AutoGPT).
3. Execution Limits (Mandatory)
The agent MUST enforce the following limits:
MAX_STEPS = 30
MAX_RETRIES_PER_STEP = 3
MAX_OUTPUT_CHARS = 2000
MAX_CONTEXT_MESSAGES = 20

MAX_AGENT_DEPTH = 3
MAX_CHILD_AGENTS = 5
CHILD_AGENT_TIMEOUT = 60  # seconds
If any limit is reached, the agent MUST terminate with a final_answer.
4. CLI Interface
python agent.py --agent agent_name --prompt "Your task here" [--model gpt-5.4]
Arguments:
--agent (required): agent name
--prompt (required): initial user input
--model (optional): overrides config model
5. Agent Configuration File (agents/agent_name.yaml)
Required structure:
role: "coder"
model: "gpt-5.4"
temperature: 0.7
max_tokens: 4096

permissions:
  - read_file
  - write_file
  - append_to_file
  - linux_command
  - run_agent
  - ls

base_system_prompt: ""

limits:
  max_steps: 30
  max_depth: 3
  max_children: 5
6. Command System
Commands are Python modules located in /commands.
Each command module MUST define:
COMMAND_NAME: str
DESCRIPTION: str
USAGE_EXAMPLE: str

def execute(parameters: dict) -> str:
    """
    Executes the command and returns a short observation string.
    Must never raise exceptions.
    Must always return a string.
    """
Command Constraints
Output MUST be ≤ MAX_OUTPUT_CHARS
Errors MUST be returned as:
ERROR: <message>
No exceptions should propagate outside the command
7. Supported Commands (Required)
read_file
write_file
append_to_file
linux_command
run_agent
ls
8. Dynamic Command and Agents Loading
At startup:
Discover all modules in /commands and /agents
Validate required attributes
Filter commands based on permissions in config
Ignore invalid or broken modules safely
9. System Prompt Construction
The agent MUST construct a system prompt including:
Role definition
Full list of allowed commands (name, description, usage)
Strict JSON interaction contract
Required Contract
You are a {role} agent.

You have ONLY TWO possible actions:

1. Execute a command:
{
  "action": "command",
  "name": "command_name",
  "parameters": { ... }
}

2. Provide final answer:
{
  "action": "final_answer",
  "content": "complete response"
}

CRITICAL RULES:
- Output EXACTLY ONE JSON object
- NO extra text before or after JSON
- NO multiple JSON objects
- NO explanations outside JSON

STRATEGY:
- Avoid repeating the same action more than twice
- If no progress is made, produce final_answer
- Prefer minimal steps

ERROR HANDLING:
- If a command fails, try a different approach
- Do NOT repeat failed commands with identical parameters

SAFETY:
- Do NOT execute destructive or dangerous system commands
10. Main Interaction Loop (ReAct)
The agent MUST:
Send system prompt + history to OpenAI (streaming enabled)
Collect full response
Extract the FIRST valid JSON object
Validate structure
If parsing fails:
Retry up to MAX_RETRIES_PER_STEP
Append error message to history:
Previous response contained error.
You MUST output exactly one valid JSON.

Last error:
<details>
11. JSON Parsing (Robust)
Parsing MUST NOT rely solely on regex.
Required approach:
Find first {
Extract JSON using bracket balancing
Attempt json.loads
If failed:
Remove trailing commas
Replace single quotes with double quotes
Retry parsing
Only the FIRST valid JSON object is used.
12. Command Execution Flow
If action == "command":
Validate command is allowed
Execute command
Truncate output if necessary
Append to history:
Observation: <result>
13. Final Answer
If action == "final_answer":
Print content
Exit immediately
14. Loop Detection (Mandatory)
Agent MUST detect repetition:
Track last 3 actions
If identical → force termination with final answer
Also detect:
Same command + same parameters repeated
15. Context Management
Maintain bounded context:
history = history[-MAX_CONTEXT_MESSAGES:]
Large outputs MUST be truncated.
16. run_agent Command (Hierarchical Execution)
Parameters:
{
  "role": "reviewer",
  "prompt": "...",
  "agent": "agent name"
}
Constraints:
Depth ≤ MAX_AGENT_DEPTH
Total children ≤ MAX_CHILD_AGENTS
Timeout enforced (CHILD_AGENT_TIMEOUT)
Execution:
Use subprocess or recursive call
Capture output
Extract only final answer
Return format:
FINAL_ANSWER: <child result>
No logs or intermediate steps allowed.
17. linux_command Safety
The agent MUST restrict dangerous commands.
Blocked patterns:
[
  "rm -rf",
  "shutdown",
  "reboot",
  "mkfs",
  ":(){ :|:& };:"
]
Additional constraints:
Execution timeout (≤ 10s)
Capture stdout + stderr
Output truncation enforced
18. Error Handling
All failures MUST:
Be converted into string responses
Never crash the agent
Trigger retry logic if needed
19. Logging
The agent MUST log all activity in structured JSONL format:
{
  "step": 1,
  "action": "read_file",
  "parameters": {...},
  "result": "...",
  "timestamp": "..."
}
