from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROMPT_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "save-prompt" / "hook.py"
PLAN_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "save-plan" / "hook.py"
MEMORY_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "record-memory" / "hook.py"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo: Path, origin: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tester@example.com")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "remote", "add", "origin", origin)
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "init")


def run_hook(
    repo: Path,
    hook: Path,
    payload: dict,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(hook), *args],
        cwd=repo,
        env=env,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"hook failed with {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def last_subject(repo: Path) -> str:
    return run_git(repo, "log", "-1", "--pretty=%s").stdout.strip()


CODEX_FORWARDED_PLAN_PREFIX = (
    "A previous agent produced the plan below to accomplish the user's task. "
    "Implement the plan in a fresh context. Treat the plan as the source of user intent, "
    "re-read files as needed, and carry the work through implementation and verification."
)


def long_plan(title: str = "Saved Plan") -> str:
    lines = [
        f"# {title}",
        "",
        "## Summary",
        "This plan is intentionally long enough to look like a real captured plan file.",
        "",
        "## Implementation",
    ]
    lines.extend(
        f"- Step {i}: preserve the relevant behavior while avoiding duplicate prompt logging."
        for i in range(1, 18)
    )
    lines.extend(
        [
            "",
            "## Tests",
            "- Verify exact-prefix stripping.",
            "- Verify changed-prefix fallback stripping.",
            "- Verify Claude pass-through.",
        ]
    )
    return "\n".join(lines) + "\n"


def claude_github_worker_prompt(
    *,
    title: str,
    body: str,
    issue_number: int = 3,
    trigger_comment: str = "",
) -> str:
    trigger_block = (
        f"<trigger_comment>\n{trigger_comment}\n</trigger_comment>\n"
        if trigger_comment
        else ""
    )
    return (
        "You are Claude, an AI assistant designed to help with GitHub issues and pull requests. "
        "Think carefully as you analyze the context and respond appropriately. "
        "Here's the context for your current task:\n\n"
        "<formatted_context>\n"
        f"Issue Title: {title}\n"
        "Issue Author: luckydonald\n"
        "Issue State: OPEN\n"
        "Issue Labels: none\n"
        "</formatted_context>\n\n"
        f"<pr_or_issue_body>\n{body}\n</pr_or_issue_body>\n\n"
        "<event_type>ISSUE_CREATED</event_type>\n"
        "<is_pr>false</is_pr>\n"
        "<trigger_context>new issue with '@claude' in body</trigger_context>\n"
        "<repository>luckydonald/AllMyStorage</repository>\n\n"
        f"<issue_number>{issue_number}</issue_number>\n"
        "<claude_comment_id>4756572381</claude_comment_id>\n"
        "<trigger_username>luckydonald</trigger_username>\n"
        "<trigger_display_name>Lucky Lucy</trigger_display_name>\n"
        "<trigger_phrase>@claude</trigger_phrase>\n"
        f"{trigger_block}"
        "IMPORTANT: Use the mcp__github_comment__update_claude_comment tool to update your comment.\n\n"
        "Your task is to analyze the context, understand the request, and provide helpful responses "
        "and/or implement code changes as needed.\n\n"
        "Before taking any action, conduct your analysis inside <analysis> tags:\n"
        "a. Summarize the event type and context\n"
        "b. Determine if this is a request for code review feedback or for implementation\n"
    )


class AiHooksBaseRoutingTests(unittest.TestCase):
    def test_codex_prompt_in_base_repo_with_only_origin_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Capture this prompt"}, "codex")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "› Capture this prompt\n\n",
            )
            self.assertFalse((repo / "ai" / "query.md").exists())
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_prompt_logs_plan_link_for_exact_forwarded_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan = long_plan("Forwarded Plan")
            plan_path = repo / "ai" / "°base" / "plans" / "001_forwarded-plan.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(plan, encoding="utf-8")

            run_hook(
                repo,
                PROMPT_HOOK,
                {"prompt": f"{CODEX_FORWARDED_PLAN_PREFIX}\n\n{plan}"},
                "codex",
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> › Implement the [Plan](./plans/001_forwarded-plan.md). <kbd>cleared</kbd>\n\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_prompt_logs_only_instruction_after_exact_forwarded_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan = long_plan("Instruction Plan")
            plan_path = repo / "ai" / "°base" / "plans" / "001_instruction-plan.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(plan, encoding="utf-8")

            run_hook(
                repo,
                PROMPT_HOOK,
                {
                    "prompt": (
                        f"{CODEX_FORWARDED_PLAN_PREFIX}\n\n"
                        f"{plan}\n"
                        "Also make the warning actionable."
                    )
                },
                "codex",
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> › Implement the [Plan](./plans/001_instruction-plan.md). <kbd>cleared</kbd>\n\n"
                "› Also make the warning actionable.\n\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_prompt_strips_changed_prefix_by_saved_plan_match_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            old_plan = long_plan("Older Plan")
            latest_plan = long_plan("Latest Plan")
            plans_dir = repo / "ai" / "°base" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "001_older-plan.md").write_text(old_plan, encoding="utf-8")
            (plans_dir / "002_latest-plan.md").write_text(latest_plan, encoding="utf-8")

            result = run_hook(
                repo,
                PROMPT_HOOK,
                {
                    "prompt": (
                        "A previous agent made a plan. Start from this updated handoff text.\n\n"
                        f"{latest_plan}\n"
                        "Keep the fallback Codex-only."
                    )
                },
                "codex",
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> › Implement the [Plan](./plans/002_latest-plan.md). <kbd>cleared</kbd>\n\n"
                "› Keep the fallback Codex-only.\n\n",
            )
            self.assertIn("prompt prefix may have changed", result.stderr)
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_prompt_does_not_file_match_tiny_latest_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            tiny_plan = "# Tiny Plan\n\nToo small.\n"
            plan_path = repo / "ai" / "°base" / "plans" / "001_tiny-plan.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(tiny_plan, encoding="utf-8")
            prompt = (
                "A previous agent made a plan. Start from this updated handoff text.\n\n"
                f"{tiny_plan}"
            )

            result = run_hook(repo, PROMPT_HOOK, {"prompt": prompt}, "codex")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                f"› {prompt}\n\n",
            )
            self.assertEqual(result.stderr, "")
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_short_plan_prompt_logs_latest_plan_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            old_plan = long_plan("Old Session Plan")
            latest_plan = long_plan("Non Resetting Session Plan")
            plans_dir = repo / "ai" / "°base" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "001_old-session-plan.md").write_text(old_plan, encoding="utf-8")
            (plans_dir / "002_non-resetting-session-plan.md").write_text(
                latest_plan,
                encoding="utf-8",
            )

            result = run_hook(repo, PROMPT_HOOK, {"prompt": "Implement the plan."}, "codex")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> › Implement the [Plan](./plans/002_non-resetting-session-plan.md).\n\n",
            )
            self.assertEqual(result.stderr, "")
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_short_plan_prompt_does_not_link_tiny_latest_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan_path = repo / "ai" / "°base" / "plans" / "001_tiny-plan.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text("# Tiny Plan\n\nToo small.\n", encoding="utf-8")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Implement the plan."}, "codex")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "› Implement the plan.\n\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_claude_short_plan_prompt_logs_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan = long_plan("Claude Short Prompt Plan")
            plan_path = repo / "ai" / "°base" / "plans" / "001_claude-short-prompt-plan.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(plan, encoding="utf-8")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Implement the plan."}, "claude")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "❯ Implement the plan.\n\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_claude_prompt_logs_forwarded_plan_text_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan = long_plan("Claude Pass Through")
            plan_path = repo / "ai" / "°base" / "plans" / "001_claude-pass-through.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(plan, encoding="utf-8")
            prompt = f"{CODEX_FORWARDED_PLAN_PREFIX}\n\n{plan}"

            run_hook(repo, PROMPT_HOOK, {"prompt": prompt}, "claude")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                f"❯ {prompt}\n\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_claude_github_worker_prompt_logs_issue_request_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            body = (
                "It seems the issue is that the API uses a get request.\n\n"
                "Maybe that flow is not yet fully implemented in the barcode add overlay?\n\n"
                "@claude"
            )

            run_hook(
                repo,
                PROMPT_HOOK,
                {
                    "prompt": claude_github_worker_prompt(
                        title="Can't add barcodes",
                        body=body,
                        issue_number=3,
                    )
                },
                "claude",
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> ❯ [query](./plans/000_online_query.md) for issue "
                "[#3](https://github.com/luckydonald/AllMyStorage/issues/3):\n"
                "> type: `ISSUE_CREATED`\n"
                "> trigger: @luckydonald (Lucky Lucy) via _@claude_.\n"
                "> comment: (none)\n"
                "> It seems the issue is that the API uses a get request.\n"
                ">\n"
                "> Maybe that flow is not yet fully implemented in the barcode add overlay?\n\n",
            )
            self.assertEqual(
                (repo / "ai" / "°base" / "plans" / "000_online_query.md").read_text(
                    encoding="utf-8",
                ),
                "# Online Query\n\n"
                "Issue: #3 Can't add barcodes\n"
                "URL: https://github.com/luckydonald/AllMyStorage/issues/3\n"
                "Event type: ISSUE_CREATED\n"
                "Trigger: @luckydonald (Lucky Lucy) via @claude\n\n"
                "## Trigger Comment\n\n"
                "(none)\n\n"
                "## Query\n\n"
                "It seems the issue is that the API uses a get request.\n\n"
                "Maybe that flow is not yet fully implemented in the barcode add overlay?\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_claude_github_worker_prompt_prefers_trigger_comment_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")

            run_hook(
                repo,
                PROMPT_HOOK,
                {
                    "prompt": claude_github_worker_prompt(
                        title="Page does not install as app on ios",
                        body="It should not open in the normal safari browser.",
                        issue_number=4,
                        trigger_comment="@claude\nPlease check the PWA manifest only.",
                    )
                },
                "claude",
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "> ❯ [query](./plans/000_online_query.md) for issue "
                "[#4](https://github.com/luckydonald/AllMyStorage/issues/4):\n"
                "> type: `ISSUE_CREATED`\n"
                "> trigger: @luckydonald (Lucky Lucy) via _@claude_.\n"
                "> comment: @claude\n"
                "> Please check the PWA manifest only.\n"
                "> Please check the PWA manifest only.\n\n",
            )
            self.assertEqual(
                (repo / "ai" / "°base" / "plans" / "000_online_query.md").read_text(
                    encoding="utf-8",
                ),
                "# Online Query\n\n"
                "Issue: #4 Page does not install as app on ios\n"
                "URL: https://github.com/luckydonald/AllMyStorage/issues/4\n"
                "Event type: ISSUE_CREATED\n"
                "Trigger: @luckydonald (Lucky Lucy) via @claude\n\n"
                "## Trigger Comment\n\n"
                "@claude\n"
                "Please check the PWA manifest only.\n\n"
                "## Query\n\n"
                "Please check the PWA manifest only.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_claude_task_notification_writes_agent_files_and_summary_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            output_file = Path(tmp) / "agent.output"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            output_file.write_text(
                json.dumps(
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_test",
                                    "name": "Agent",
                                    "input": {"prompt": "Inspect the compose window."},
                                }
                            ]
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_hook(
                repo,
                PROMPT_HOOK,
                {
                    "prompt": (
                        "<task-notification>\n"
                        "<task-id>a6f364ce63ffebb84</task-id>\n"
                        "<tool-use-id>toolu_test</tool-use-id>\n"
                        f"<output-file>{output_file}</output-file>\n"
                        "<status>completed</status>\n"
                        "<summary>Agent came to rest</summary>\n"
                        "<result>Done.</result>\n"
                        "<usage><subagent_tokens>67643</subagent_tokens>"
                        "<tool_uses>6</tool_uses><duration_ms>69837</duration_ms></usage>\n"
                        "</task-notification>"
                    )
                },
                "claude",
            )

            agent_dir = repo / "ai" / "°base" / "agents" / "001.a6f364ce63ffebb84"
            self.assertEqual(
                (agent_dir / "prompt.md").read_text(encoding="utf-8"),
                "Inspect the compose window.",
            )
            self.assertEqual((agent_dir / "result.md").read_text(encoding="utf-8"), "Done.")
            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "❯ Task Notification:\n"
                "> - Task `a6f364ce63ffebb84` <kbd>completed</kbd>\n"
                "> - Tool `toolu_test`\n"
                "> - > Agent came to rest\n"
                "> - [Query (`27` chars, `27 B`)](agents/001.a6f364ce63ffebb84/prompt.md)\n"
                "> - [Answer (`5` chars, `5 B`)](agents/001.a6f364ce63ffebb84/result.md)\n"
                f"> - [Raw log (`{len(output_file.read_text(encoding='utf-8'))}` chars, "
                f"`{output_file.stat().st_size} B`)]({output_file})\n"
                "> - `6` tools, `67643` tokens, `1.16395 s`\n"
                "\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_plan_in_base_repo_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            session_id = f"test-{uuid.uuid4()}"

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "Stop",
                    "session_id": session_id,
                    "last_assistant_message": (
                        "<proposed_plan>\n"
                        "# Base Route Plan\n"
                        "Write the routed plan artifact.\n"
                        "</proposed_plan>"
                    ),
                },
                "codex",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_base-route-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Base Route Plan\nWrite the routed plan artifact.\n",
            )
            self.assertFalse((repo / "ai" / "plans").exists())
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_base-route-plan")

    def test_codex_plan_ignores_post_tool_use_stdout_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": f"test-{uuid.uuid4()}",
                    "tool_name": "ExitPlanMode",
                    "tool_response": "Exit code: 0\nstdout from some command\n",
                },
                "codex",
            )

            self.assertFalse((repo / "ai" / "°base" / "plans").exists())
            self.assertEqual(last_subject(repo), "init")

    def test_codex_plan_uses_session_transcript_plan_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            session_id = f"test-{uuid.uuid4()}"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            session_dir = home / ".codex" / "sessions" / "2026" / "05" / "27"
            session_dir.mkdir(parents=True)
            session_file = session_dir / f"rollout-2026-05-27T14-20-27-{session_id}.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "item": {
                                "type": "Plan",
                                "text": "# Transcript Plan\n\nUse the Codex plan event.\n",
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_hook(
                repo,
                PLAN_HOOK,
                {"hook_event_name": "Stop", "session_id": session_id},
                "codex",
                extra_env={"HOME": str(home)},
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_transcript-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Transcript Plan\n\nUse the Codex plan event.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_transcript-plan")

    def test_codex_plan_falls_back_to_forwarded_plan_query_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            query_path = repo / "ai" / "°base" / "query.md"
            query_path.parent.mkdir(parents=True)
            query_path.write_text(
                "› A previous agent produced the plan below to accomplish the user's task.\n"
                "Implement the plan in a fresh context.\n\n"
                "# Forwarded Plan\n\n"
                "Save this markdown plan.\n\n",
                encoding="utf-8",
            )

            run_hook(
                repo,
                PLAN_HOOK,
                {"hook_event_name": "Stop", "session_id": f"test-{uuid.uuid4()}"},
                "codex",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_forwarded-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Forwarded Plan\n\nSave this markdown plan.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_forwarded-plan")

    def test_claude_write_plan_still_captures_claude_plan_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan_file = home / ".claude" / "plans" / "test-plan.md"

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": f"test-{uuid.uuid4()}",
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(plan_file),
                        "content": "# Claude Write Plan\n\nKeep Claude behavior.\n",
                    },
                },
                "claude",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_claude-write-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Claude Write Plan\n\nKeep Claude behavior.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_claude-write-plan")

    def test_memory_in_base_repo_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            encoded = str(repo).replace("/", "-")
            src_dir = home / ".claude" / "projects" / encoded / "memory"
            src_dir.mkdir(parents=True)
            (src_dir / "note.md").write_text("remember this\n", encoding="utf-8")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "memory" / "note.md").read_text(encoding="utf-8"),
                "remember this\n",
            )
            self.assertFalse((repo / "ai" / "memory").exists())
            self.assertEqual(last_subject(repo), "[base] ai: record memory note")

    def test_memory_session_start_restores_missing_claude_source_from_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            memory_file = repo / "ai" / "°base" / "memory" / "note.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text("repo is durable\n", encoding="utf-8")
            run_git(repo, "add", str(memory_file.relative_to(repo)))
            run_git(repo, "commit", "-m", "seed memory")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            encoded = str(repo).replace("/", "-")
            src_file = home / ".claude" / "projects" / encoded / "memory" / "note.md"
            self.assertEqual(src_file.read_text(encoding="utf-8"), "repo is durable\n")
            self.assertEqual(last_subject(repo), "seed memory")

    def test_memory_session_start_does_not_resurrect_marked_deleted_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            memory_file = repo / "ai" / "°base" / "memory" / "old.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text("old memory\n", encoding="utf-8")
            run_git(repo, "add", str(memory_file.relative_to(repo)))
            run_git(repo, "commit", "-m", "seed old memory")
            run_git(repo, "rm", str(memory_file.relative_to(repo)))
            run_git(
                repo,
                "commit",
                "-m",
                "ai: delete memory old",
                "-m",
                "Deleted Memory: old.md",
            )
            encoded = str(repo).replace("/", "-")
            src_file = home / ".claude" / "projects" / encoded / "memory" / "old.md"
            src_file.parent.mkdir(parents=True)
            src_file.write_text("stale local memory\n", encoding="utf-8")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            self.assertFalse(memory_file.exists())
            self.assertFalse(src_file.exists())
            self.assertEqual(last_subject(repo), "ai: delete memory old")

    def test_prompt_in_repo_named_base_with_different_origin_is_unprefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://github.com/example/consumer.git")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Capture downstream prompt"}, "codex")

            self.assertEqual(
                (repo / "ai" / "query.md").read_text(encoding="utf-8"),
                "› Capture downstream prompt\n\n",
            )
            self.assertFalse((repo / "ai" / "°base" / "query.md").exists())
            self.assertEqual(last_subject(repo), "ai: updated prompt")


if __name__ == "__main__":
    unittest.main()
