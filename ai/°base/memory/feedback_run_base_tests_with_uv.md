---
name: feedback-run-base-tests-with-uv
description: "Run the base project's unit tests with `uv run --project scripts/°base python -m unittest …`, never the system `python3`"
metadata:
  node_type: memory
  type: feedback
  originSessionId: c6820be5-4c3e-45e9-a787-e745a08734ae
  modified: 2026-11-12T07:54:43.223Z
---

Run the base project's unit tests through uv: `uv run --project scripts/°base python -m unittest discover -s scripts/°base/tests -v`, and for one module add `-p "test_<name>.py"`.
Never use the bare system `python3 -m unittest`.

**Why:** The system Python lacks the project dependencies, so `test_settings_schema` and `test_codex_memory_registry` fail to import `jsonschema` and show up as false errors in the suite.
The user asked to record uv as the way to run them.

**How to apply:** Use the commands from `ai/°base/AGENTS.md` ("Commands"). For tests of `scripts/°base/ai/todos/`, `uv run --with pytest pytest` also works, see [[feedback-scripts-python-uv]].
