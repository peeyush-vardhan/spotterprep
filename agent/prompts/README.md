# Agent prompts

These two files are the prompt design for the production SpotterPrep agent.

| File | What it is |
|---|---|
| [`system_prompt.md`](system_prompt.md) | The agent's role, phases, tool-use rules and escalation policy |
| [`trigger_rules.md`](trigger_rules.md) | What the agent does in response to each kind of user message |

They are design artifacts, not runnable code. They assume an MCP tool server over Postgres that is not in this repository, so nothing here calls them. The code that does run is in [`spotterprep/`](../../spotterprep): Iteration 2 uses its own prompts in [`spotterprep/llm.py`](../../spotterprep/llm.py), and those are the prompts the evals measure.
