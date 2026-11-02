#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2.3", "pydantic>=2.6", "python-dotenv>=1.0"]
# ///
"""Sync the todos of the `sync_todo` CalDAV list into the todo files of other projects.

Reads the list live through the sync_todo MCP server (`list_todos`, read-only, needs the
`mcp_todos_read` scope), assigns every todo to a project by its `#Tag` prefix / category, and
merges them into that project's todo markdown file. One-way: CalDAV is the source of truth.

    uv run scripts/°base/ai/todos/sync_todos.py [--dry-run] [--no-git] [-v] [--project NAME] [--purge-missing] [--purge-complete|--purge-completed] [--include-completed|--include-complete] [--reset-todo-file] [--add-files|--add] [--config PATH] [--repo-config PATH] [--local-config PATH] [--migrate-local-paths]
    uv run scripts/°base/ai/todos/sync_todos.py --write-schema

The tag to project mapping is tracked in `ai/settings/sync_todos.json`, the schemas for IDE completion are `ai/settings/sync_todos.schema.json` and `ai/settings/sync_todos-local.schema.json`.
`ai/settings/sync_todos.repo.json` (committed, created empty on the first run) layers over it: it can set everything the tracked mapping and the local file can, with `path`s restricted to `.` / `./…` inside the repository.
Where a project lives on this machine is not tracked: `ai/settings/sync_todos.local.json` (gitignored) maps each project name to a `path` and may override its `commit_prefix`, and wins over the repo file; a `null` there falls through to the repo value.
Every run adds a `null` entry for each project that is missing there and has no repo path; a project without any path is skipped, so nothing outside the configured paths is ever written.
`--migrate-local-paths` moves the repository-internal local paths into the repo file; without it a hint lists them (silence per project with `"no-add-to-repo-hint": true` in any of the three files). Line format:

    - [ ] text — `todo:<uid>` _(state)_
      > description line

Only lines carrying a `todo:<uid>` are managed; everything else in the file is left alone. The `>` lines of a managed todo follow its CalDAV description: notes written above or below an unchanged description stay, a changed description replaces the block and the lines that go are reported.
New todos go under `## Todos synced from CalDAV` (the old `## Synced from CalDAV` still counts); a file that does not exist yet starts from `todos.template.md` next to this script, and the old bare `# Todos` header is upgraded to it; completed ones that are not in the file yet are ignored (`--include-completed`). `--purge-missing` / `--purge-complete` then clean up, each as its own commit. `--reset-todo-file` (needs `--project`, git, and a file without uncommitted changes) first rebuilds the file from the template plus its checkbox lines and their `>` rows, as its own commit; what it dropped is printed. Files that a summary or description mentions (`@path` or `` `dir/file` ``, resolved against the project's git root) and that exist are written as markdown links relative to the todo file, like `ai/prompt.md` does; `--add-files` also commits the mentioned files that have changes. Every written file is committed as
`{commit_prefix}[TODOs] synced todos for {projects}.` in the git root of each project (one commit per repo and prefix, only those files; `--no-git` skips it). If `HEAD` already is such an unpushed sync commit of the same projects that touched nothing else, it is amended instead (`--no-amend` makes a new commit).
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import functools
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema



def resolve_roots(file: str) -> tuple[Path, Path, Path, Path, Path]:
    """(git root, tracked config, its schema, local config, its schema) for the script started as `file`.

    The git root is asked from git, never guessed from a folder name, so it is the checkout the base was merged into.
    `abspath` keeps a symlinked location, `resolve()` would follow it somewhere else.
    """
    here = Path(os.path.abspath(file))
    top = subprocess.run(["git", "-C", str(here.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = Path(top.stdout.strip()) if top.returncode == 0 and top.stdout.strip() else here.parents[4]
    settings = root / "ai" / "settings"
    return root, settings / "sync_todos.json", settings / "sync_todos.schema.json", settings / "sync_todos.local.json", settings / "sync_todos-local.schema.json"
# end def


REPO_ROOT, DEFAULT_CONFIG, SCHEMA_PATH, LOCAL_CONFIG, LOCAL_SCHEMA_PATH = resolve_roots(__file__)
REPO_CONFIG = DEFAULT_CONFIG.with_name("sync_todos.repo.json")
REPO_SCHEMA_PATH = DEFAULT_CONFIG.with_name("sync_todos-repo.schema.json")
SECTION = "## Todos synced from CalDAV"
LEGACY_SECTION = "## Synced from CalDAV"
OLD_TEMPLATE_HEADER = "# Todos"
NEW_TEMPLATE_MARKER = "## For Agents"
TEMPLATE_PATH = Path(os.path.realpath(__file__)).with_name("todos.template.md")
VERBOSE = False
HOOKS_DIR = Path(os.path.abspath(__file__)).parents[1] / "hooks"
LINKED: dict[str, list[Any]] = {}  # project name -> file mentions linked while rendering, for `--add-files`


def vlog(message: str) -> None:
    """Detail about every comparison, only with --verbose."""
    if VERBOSE:
        print(f"  . {message}")
    # end if
# end def


def short(uid: str) -> str:
    return uid[:8]
# end def


HINT_DESCRIPTION = "Silences the hint to move this project's repository-internal local `path` into `sync_todos.repo.json`; true in any of the three config files counts."
REPO_PATH_PATTERN = r"^(?!.*(^|/)\.\.(/|$))\.(/.*)?$"
EMPTY_REPO_FILE = '{\n  "$schema": "./sync_todos-repo.schema.json",\n  "projects": {\n  }\n}\n'


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(description="Label, also used by --project.")
    tags: list[str] = Field(
        min_length=1,
        description="`#Tag` summary prefixes / categories that belong to this project (matched case-insensitively).",
    )
    path: SkipJsonSchema[str | None] = Field(
        default=None, exclude=True,
        description="Project root on this machine, from the local config only (null: skipped). `~` is expanded, relative paths are relative to the git root.",
    )
    todo_file: str = Field(default="ai/todos.md", description="Todo markdown file, relative to `path`.")
    commit_prefix: str | None = Field(
        default=None,
        description="Prefix of the commit message for this project, e.g. `[sync_todo] ` for a subproject. Overrides the global one, and is itself overridden by the repo and local config; null inherits it.",
    )
    path_source: SkipJsonSchema[str | None] = Field(default=None, exclude=True, description="Which file `path` came from: `repo` or `local`.")
    no_add_to_repo_hint: bool = Field(default=False, alias="no-add-to-repo-hint", description=HINT_DESCRIPTION)

    @field_validator("tags")
    @classmethod
    def tags_nonblank(cls, tags: list[str]) -> list[str]:
        if any(not t.strip() for t in tags):
            raise ValueError("tags must not be blank")
        # end if
        return tags
    # end def

    def root(self) -> Path:
        if self.path is None:
            raise ValueError(f"project {self.name!r} has no path in {LOCAL_CONFIG.name}")
        # end if
        root = Path(os.path.expanduser(self.path))
        if not root.is_absolute():
            root = REPO_ROOT / root
        # end if
        return root
    # end def

    def file(self) -> Path:
        return self.root() / self.todo_file
    # end def
# end class


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str | None = Field(default=None, alias="$schema")
    url_env: str = Field(default="SYNC_TODO_MCP_URL", description="Env var holding the MCP server URL.")
    token_env: str = Field(default="SYNC_TODO_MCP_TOKEN", description="Env var holding the bare `sytd_...` token.")
    env_file: str | None = Field(default="ai/.env", description="Env file (relative to the git root) to load first.")
    commit_prefix: str = Field(default="", description="Default prefix of the commit messages, e.g. `[root] `.")
    calendar_id: int = Field(default=7, description="Calendar to read (7 = `TODO: Today`).")
    projects: list[Project] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> "Config":
        names: set[str] = set()
        tags: dict[str, str] = {}
        for p in self.projects:
            if p.name.casefold() in names:
                raise ValueError(f"duplicate project name {p.name!r}")
            # end if
            names.add(p.name.casefold())
            for t in p.tags:
                other = tags.setdefault(t.casefold(), p.name)
                if other != p.name:
                    raise ValueError(f"tag {t!r} is used by both {other!r} and {p.name!r}")
                # end if
            # end for
        # end for
        return self
    # end def
# end class


class LocalProject(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str | None = Field(
        default=None,
        description="Project root on this machine. `~` is expanded, relative paths are relative to the git root. null: the repo config's path is used, or the project is skipped without one.",
    )
    commit_prefix: str | None = Field(default=None, description="Overrides the tracked and repo commit prefixes; null keeps them.")
    no_add_to_repo_hint: bool = Field(default=False, alias="no-add-to-repo-hint", description=HINT_DESCRIPTION)
# end class


class LocalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str | None = Field(default=None, alias="$schema")
    projects: dict[str, LocalProject] = Field(default_factory=dict, description="Project name (as in the tracked mapping) to its machine-local settings.")
# end class


class RepoProject(BaseModel):
    """What the committed repo config may say about one project: everything the tracked and the local config can, set fields only."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tags: list[str] | None = Field(default=None, min_length=1, description="Tags of the project, required when the project is not in `sync_todos.json`; replaces its tags otherwise.")
    todo_file: str | None = Field(default=None, description="Todo markdown file, relative to `path`.")
    commit_prefix: str | None = Field(default=None, description="Prefix of the commit message for this project; the local config overrides it.")
    path: str | None = Field(
        default=None,
        json_schema_extra={"pattern": REPO_PATH_PATTERN},
        description="Project root inside this repository: `.` or starting with `./`, never containing `..`. A non-null path in the local config wins.",
    )
    no_add_to_repo_hint: bool = Field(default=False, alias="no-add-to-repo-hint", description=HINT_DESCRIPTION)

    @field_validator("path")
    @classmethod
    def inside_repo(cls, path: str | None) -> str | None:
        if path is not None and not re.match(REPO_PATH_PATTERN, path):
            raise ValueError(f"path {path!r} must be `.` or start with `./`, and must not contain `..` (absolute and `~` paths belong in the local config)")
        # end if
        return path
    # end def
# end class


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str | None = Field(default=None, alias="$schema")
    url_env: str = Field(default="SYNC_TODO_MCP_URL", description="Overrides the setting of `sync_todos.json`.")
    token_env: str = Field(default="SYNC_TODO_MCP_TOKEN", description="Overrides the setting of `sync_todos.json`.")
    env_file: str | None = Field(default="ai/.env", description="Overrides the setting of `sync_todos.json`.")
    commit_prefix: str = Field(default="", description="Overrides the default prefix of the commit messages of `sync_todos.json`.")
    calendar_id: int = Field(default=7, description="Overrides the calendar of `sync_todos.json`.")
    projects: dict[str, RepoProject] = Field(default_factory=dict, description="Project name to its settings, layered over `sync_todos.json` and under the local config.")
# end class


def _schema_text(model: type[BaseModel], file_name: str, title: str) -> str:
    """The model's JSON schema, headed like the `ai/settings/settings*.schema.json` files (draft, `$id`, title)."""
    body = model.model_json_schema(by_alias=True)
    body.pop("title", None)
    head = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/luckydonald/base/ai/settings/{file_name}",
        "title": title,
    }
    return json.dumps({**head, **body}, indent=2, ensure_ascii=False) + "\n"
# end def


def schema_text() -> str:
    return _schema_text(Config, SCHEMA_PATH.name, "Tracked todo sync mapping (tags to projects)")
# end def


def local_schema_text() -> str:
    return _schema_text(LocalConfig, LOCAL_SCHEMA_PATH.name, "Machine-local todo sync settings (project paths)")
# end def


def repo_schema_text() -> str:
    return _schema_text(RepoConfig, REPO_SCHEMA_PATH.name, "Committed per-repository todo sync settings")
# end def


def dump_json(data: dict[str, Any]) -> str:
    """The usual layout: two spaces, readable unicode, trailing newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
# end def


def read_repo(repo: Path | None) -> RepoConfig:
    return RepoConfig.model_validate_json(repo.read_text(encoding="utf-8")) if repo is not None and repo.exists() else RepoConfig()
# end def


def local_data(local_config: LocalConfig) -> dict[str, Any]:
    """The local file as it is written; the hint flag only shows up when it is set."""
    return {
        "$schema": f"./{LOCAL_SCHEMA_PATH.name}",
        "projects": {
            name: {
                "path": entry.path,
                "commit_prefix": entry.commit_prefix,
                **({"no-add-to-repo-hint": True} if entry.no_add_to_repo_hint else {}),
            }
            for name, entry in local_config.projects.items()
        },
    }
# end def


def merge_repo(raw: dict[str, Any], repo_config: RepoConfig, repo_name: str, tracked_name: str) -> None:
    """Layer the set fields of the repo config over the raw tracked mapping (paths are applied later, they are not part of it)."""
    for key in ("url_env", "token_env", "env_file", "commit_prefix", "calendar_id"):
        if key in repo_config.model_fields_set:
            raw[key] = getattr(repo_config, key)
        # end if
    # end for
    by_name = {p["name"]: p for p in raw.get("projects", []) if isinstance(p, dict) and "name" in p}
    for name, entry in repo_config.projects.items():
        target = by_name.get(name)
        if target is None:
            if entry.tags is None:
                raise ValueError(f"{repo_name}: project {name!r} is not in {tracked_name}, so it needs `tags`")
            # end if
            target = {"name": name}
            raw.setdefault("projects", []).append(target)
            by_name[name] = target
        # end if
        for key, alias in (("tags", "tags"), ("todo_file", "todo_file"), ("commit_prefix", "commit_prefix"), ("no_add_to_repo_hint", "no-add-to-repo-hint")):
            if key in entry.model_fields_set:
                target[alias] = getattr(entry, key)
            # end if
        # end for
    # end for
# end def


def load_config(tracked: Path, local: Path, write_local: bool = True, repo: Path | None = None) -> Config:
    """The tracked mapping with the repo config and then the machine-local paths and prefix overrides applied.

    A `path` in the tracked file is refused (it would be wrong on every other machine).
    Missing projects are added to the local file with `null` values, unless the repo config already gives them a path; existing values are never touched.
    A local `null` falls through to the repo value, a non-null local value wins.
    """
    raw = json.loads(tracked.read_text(encoding="utf-8"))
    for project in raw.get("projects", []):
        if isinstance(project, dict) and "path" in project:
            raise ValueError(f"{tracked.name}: project {project.get('name')!r} has a `path`, put it into {local.name} or {REPO_CONFIG.name} instead")
        # end if
    # end for
    repo_config = read_repo(repo)
    if repo is not None:
        merge_repo(raw, repo_config, repo.name, tracked.name)
    # end if
    config = Config.model_validate(raw)
    local_config = LocalConfig.model_validate_json(local.read_text(encoding="utf-8")) if local.exists() else LocalConfig()
    added = [
        p.name for p in config.projects
        if p.name not in local_config.projects and not (p.name in repo_config.projects and repo_config.projects[p.name].path is not None)
    ]
    for name in added:
        local_config.projects[name] = LocalProject()
    # end for
    if added and write_local:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(dump_json(local_data(local_config)), encoding="utf-8")
        print(f"added {', '.join(added)} to {local.name} with a null path (set one to enable the project, or put it into {REPO_CONFIG.name})", file=sys.stderr)
    # end if
    stale = sorted(set(local_config.projects) - {p.name for p in config.projects})
    if stale:
        print(f"{local.name} has projects that are not in {tracked.name}: {', '.join(stale)}", file=sys.stderr)
    # end if
    for project in config.projects:
        entry = local_config.projects.get(project.name, LocalProject())
        repo_entry = repo_config.projects.get(project.name)
        if repo_entry is not None and repo_entry.path is not None:
            project.path, project.path_source = repo_entry.path, "repo"
        # end if
        if entry.path is not None:
            project.path, project.path_source = entry.path, "local"
        # end if
        if entry.commit_prefix is not None:
            project.commit_prefix = entry.commit_prefix
        # end if
        if entry.no_add_to_repo_hint:
            project.no_add_to_repo_hint = True
        # end if
    # end for
    return config
# end def


def internal_path(path: str | None) -> str | None:
    """`.` or `./sub/dir` for a local path that lies inside this repository (and has no `..` in it), otherwise None."""
    if path is None or ".." in Path(path).parts:
        return None
    # end if
    expanded = Path(os.path.expanduser(path))
    root = Path(os.path.abspath(expanded if expanded.is_absolute() else REPO_ROOT / expanded))
    try:
        relative = root.relative_to(os.path.abspath(REPO_ROOT))
    except ValueError:
        return None
    # end try
    return "." if relative == Path(".") else f"./{relative.as_posix()}"
# end def


def movable(config: Config, repo: Path) -> dict[str, str]:
    """Project name to the `./…` path, for projects whose path comes from the local file, lies inside the repository, and has no path in the repo config yet."""
    repo_config = read_repo(repo)
    moves: dict[str, str] = {}
    for project in config.projects:
        converted = internal_path(project.path) if project.path_source == "local" else None
        if converted is None:
            continue
        # end if
        if name_has_repo_path(repo_config, project.name):
            continue
        # end if
        moves[project.name] = converted
    # end for
    return moves
# end def


def name_has_repo_path(repo_config: RepoConfig, name: str) -> bool:
    entry = repo_config.projects.get(name)
    return entry is not None and entry.path is not None
# end def


def commit_file(path: Path, subject: str) -> None:
    """Commit only `path`, in the git root that contains it."""
    top = git(path.parent, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print(f"{path.name} is not in a git repo, not committing", file=sys.stderr)
        return
    # end if
    root = Path(top.stdout.strip())
    relative = str(path.resolve().relative_to(root.resolve()))
    added = git(root, "add", "--", relative)
    if added.returncode != 0:
        print(f"git add failed: {added.stderr.strip()}", file=sys.stderr)
        return
    # end if
    if git(root, "diff", "--cached", "--quiet", "--", relative).returncode == 0:
        vlog(f"{relative}: nothing staged in {root}, no commit")
        return
    # end if
    done = git(root, "commit", "-m", subject, "--", relative)
    if done.returncode != 0:
        print(f"git commit failed: {done.stderr.strip() or done.stdout.strip()}", file=sys.stderr)
    else:
        print(f"committed {git(root, 'rev-parse', '--short=9', 'HEAD').stdout.strip()} in {root}: {subject}")
    # end if
# end def


def repo_prefix(config: Config) -> str:
    """Commit prefix for changes of the repo config itself: the one of the project that lives in the repository root, else the default."""
    for project in config.projects:
        if project.path is not None and internal_path(project.path) == "." and project.commit_prefix is not None:
            return project.commit_prefix
        # end if
    # end for
    return config.commit_prefix
# end def


def ensure_repo_file(repo: Path, prefix: str, dry_run: bool, use_git: bool) -> None:
    """Create the empty repo config when it is missing, and commit it on its own."""
    if repo.exists():
        return
    # end if
    if dry_run:
        print(f"would create {repo}")
        return
    # end if
    repo.parent.mkdir(parents=True, exist_ok=True)
    repo.write_text(EMPTY_REPO_FILE, encoding="utf-8")
    print(f"created {repo}")
    if use_git:
        commit_file(repo, f"{prefix}[TODOs] added {repo.name}.")
    # end if
# end def


def migrate_local_paths(config: Config, repo: Path, local: Path, only: set[str], dry_run: bool, use_git: bool) -> list[str]:
    """Move the repository-internal local paths (and the commit prefixes next to them) of `only` into the repo config.

    The repo file is committed on its own, the local one is ignored by git. Returns the names that were moved.
    """
    moves = {name: path for name, path in movable(config, repo).items() if name in only}
    if not moves:
        return []
    # end if
    repo_data = json.loads(repo.read_text(encoding="utf-8")) if repo.exists() else json.loads(EMPTY_REPO_FILE)
    local_config = LocalConfig.model_validate_json(local.read_text(encoding="utf-8"))
    projects = repo_data.setdefault("projects", {})
    for name, path in moves.items():
        entry = projects.setdefault(name, {})
        entry["path"] = path
        local_entry = local_config.projects[name]
        if local_entry.commit_prefix is not None and "commit_prefix" not in entry:
            entry["commit_prefix"] = local_entry.commit_prefix
            local_entry.commit_prefix = None
        # end if
        local_entry.path = None
        print(f"[{name}] moves path {path} into {repo.name}")
    # end for
    if dry_run:
        return list(moves)
    # end if
    repo.write_text(dump_json(repo_data), encoding="utf-8")
    local.write_text(dump_json(local_data(local_config)), encoding="utf-8")
    if use_git:
        commit_file(repo, f"{repo_prefix(config)}[TODOs] moved local project paths into {repo.name} for {', '.join(moves)}.")
    # end if
    return list(moves)
# end def


def entry_lines(path: Path, name: str, as_list: bool) -> tuple[list[int], int | None]:
    """(1-based lines of the entry of project `name`, line of the `projects` key) in a config file; as_list: tracked file with `{"name": …}` items."""
    if not path.exists():
        return [], None
    # end if
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = re.compile(r'"name"\s*:\s*' + re.escape(json.dumps(name)) if as_list else re.escape(json.dumps(name)) + r"\s*:\s*\{")
    found = [i + 1 for i, line in enumerate(lines) if entry.search(line)]
    key = next((i + 1 for i, line in enumerate(lines) if re.search(r'"projects"\s*:', line)), None)
    return found, key
# end def


def add_to_repo_hint(config: Config, moves: dict[str, str], tracked: Path, repo: Path, local: Path) -> list[str]:
    """The hint text for projects that could move their local path into the repo config, with the places to edit; empty if none or all silenced."""
    names = [p.name for p in config.projects if p.name in moves and not p.no_add_to_repo_hint]
    if not names:
        return []
    # end if
    out = [
        f"{len(names)} project path(s) in {local.name} lie inside this repository and could be committed in {repo} instead.",
        "Rerun with --migrate-local-paths to move them, or add them to the repo file by hand as {\"<name>\": {\"path\": \"./<dir>\"}} under \"projects\".",
        'To keep them local, silence this per project with "no-add-to-repo-hint": true in its entry in any one of:',
        f"  {tracked} (list item: {{\"name\": \"<name>\", \"no-add-to-repo-hint\": true, …}})",
        f"  {repo} and {local} (under \"projects\": {{\"<name>\": {{\"no-add-to-repo-hint\": true, …}}}})",
    ]
    for name in names:
        out.append(f"  {name} (path {moves[name]}):")
        for file, as_list in ((tracked, True), (repo, False), (local, False)):
            found, key = entry_lines(file, name, as_list)
            if found:
                out += [f"    {file}:{line}" for line in found]
            else:
                out.append(f"    {file}:{key} (add here)" if key is not None else f"    {file} (add here)")
            # end if
        # end for
    # end for
    return out
# end def


# --------------------------------------------------------------------------- assignment

PREFIX = re.compile(r"^\s*#(\w[\w-]*)\s*")


def todo_tags(todo: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    m = PREFIX.match(todo.get("summary") or "")
    if m:
        found.add(m.group(1).casefold())
    # end if
    for c in todo.get("categories") or []:
        c = c.strip()
        if c.casefold().startswith("category:"):
            c = c.split(":", 1)[1].strip()
        # end if
        found.add(c.lstrip("#").casefold())
    # end for
    return found
# end def


def assign(todos: list[dict[str, Any]], projects: list[Project]) -> dict[str, list[dict[str, Any]]]:
    """Project name -> its todos (CalDAV order). Untagged subtasks inherit from their parent."""
    by_uid = {t["uid"]: t for t in todos}
    owner: dict[str, str | None] = {}

    def resolve(todo: dict[str, Any], seen: frozenset[str] = frozenset()) -> str | None:
        uid = todo["uid"]
        if uid in owner:
            return owner[uid]
        # end if
        tags = todo_tags(todo)
        result = next((p.name for p in projects if tags & {t.casefold() for t in p.tags}), None)
        parent = by_uid.get(todo.get("parent_uid") or "")
        if result is None and parent is not None and uid not in seen:
            result = resolve(parent, seen | {uid})
        # end if
        owner[uid] = result
        via = "tags " + ",".join(sorted(tags)) if tags else "no tags"
        vlog(f"assign {short(uid)} {(todo.get('summary') or '')[:40]!r}: {via} -> {result or 'nobody'}"
             + (" (inherited from parent)" if result and not tags & {t.casefold() for p in projects if p.name == result for t in p.tags} else ""))
        return result
    # end def

    out: dict[str, list[dict[str, Any]]] = {p.name: [] for p in projects}
    for todo in todos:
        name = resolve(todo)
        if name:
            out[name].append(todo)
        # end if
    # end for
    return out
# end def


# --------------------------------------------------------------------------- rendering

@functools.cache
def reffiles() -> Any | None:
    """The `°reffiles_lib` of the base hooks (the one that links files in `ai/prompt.md`), None if the base is not checked out."""
    if not HOOKS_DIR.is_dir():
        vlog(f"{HOOKS_DIR} not found, file mentions stay plain text")
        return None
    # end if
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    # end if
    try:
        return importlib.import_module("°reffiles_lib")
    except ImportError as e:
        vlog(f"°reffiles_lib not importable ({e}), file mentions stay plain text")
        return None
# end def


def link_root(project: Project) -> Path:
    """Git root of the project (mentions are resolved against it), else the project root."""
    top = git(project.root(), "rev-parse", "--show-toplevel")
    return Path(top.stdout.strip()) if top.returncode == 0 else project.root()
# end def


def link_files(text: str, project: Project) -> str:
    """Turn `@path` / `` `dir/file` `` mentions of existing files into markdown links relative to the project's todo file, like the
    `ai/prompt.md` hook does. Applied to the CalDAV text before it is compared or written, so both sides stay equal and a sync is idempotent."""
    lib = reffiles()
    if lib is None or "/" not in text:
        return text
    # end if
    root = link_root(project)
    here = os.getcwd()
    os.chdir(root)  # the library resolves against the cwd
    try:
        linked, resolved = lib.process_referenced_files(text, root, project.file())
    finally:
        os.chdir(here)
    if resolved:
        LINKED.setdefault(project.name, []).extend(resolved)
    # end if
    return linked
# end def


def commit_mentions(project: Project) -> None:
    """`--add-files`: stage and commit the files the todos of `project` mention (those with changes, as the prompt.md hook does)."""
    lib = reffiles()
    mentions = LINKED.get(project.name)
    if lib is None or not mentions:
        return
    # end if
    here = os.getcwd()
    os.chdir(link_root(project))
    try:
        lib.stage_and_commit_mentions(mentions)
    finally:
        os.chdir(here)
# end def


def clean_summary(todo: dict[str, Any], project: Project) -> str:
    text = " ".join((todo.get("summary") or "").split())
    m = PREFIX.match(text)
    if m and m.group(1).casefold() in {t.casefold() for t in project.tags}:
        text = text[m.end():]
    # end if
    return link_files(text, project) if text else "(no title)"
# end def


PRIORITY_WORDS = {1: "highest", 2: "high", 3: "high", 4: "high", 5: "medium", 6: "low", 7: "low", 8: "low", 9: "lowest"}
PRIORITY = r"prio \d₍₉₎ (?:highest|high|medium|low|lowest)"


def priority_text(todo: dict[str, Any]) -> str:
    """`prio 1₍₉₎ highest`: iCal priority `1` is the highest, `9` the lowest; unset (`0`, `null`) gives nothing."""
    priority = todo.get("priority")
    if not isinstance(priority, int) or priority not in PRIORITY_WORDS:
        return ""
    # end if
    return f"prio {priority}₍₉₎ {PRIORITY_WORDS[priority]}"
# end def


NOT_OPEN_STATUSES = frozenset({"COMPLETED", "CANCELLED", "DELEGATED"})  # done, deferred, waiting on someone else


def count_open(todos: list[dict[str, Any]]) -> int:
    """How many of the todos still wait for the user: neither done, nor deferred, nor delegated."""
    return sum(1 for todo in todos if todo.get("status") not in NOT_OPEN_STATUSES)
# end def


def checkbox_and_state(todo: dict[str, Any]) -> tuple[str, str]:
    """The checkbox char and the `_(status; priority)_` marker, either part left out if there is none."""
    status = todo.get("status")
    pct = todo.get("percent_complete")
    box, text = " ", ""
    if status == "COMPLETED":
        box, text = "x", "done"
    elif status == "CANCELLED":
        box, text = "-", "cancelled"
    elif status == "IN-PROCESS":
        box, text = "…", f"in process, {pct}%" if pct else "in process"
    elif status == "NEEDS-ACTION":
        box, text = "!", "needs action"
    # end if
    inner = "; ".join(part for part in (text, priority_text(todo)) if part)
    return box, f"_({inner})_" if inner else ""
# end def


def render(todo: dict[str, Any], project: Project, indent: int = 0) -> list[str]:
    box, state = checkbox_and_state(todo)
    pad = " " * indent
    head = f"{pad}- [{box}] {clean_summary(todo, project)} — `todo:{todo['uid']}`"
    if state:
        head += f" {state}"
    # end if
    lines = [head]
    for line in link_files((todo.get("description") or "").strip(), project).splitlines():
        lines.append(f"{pad}  > {line}".rstrip())
    # end for
    return lines
# end def


STATE = re.compile(rf"\s*_\((?:(?:done|cancelled|needs action|in process[^)]*|missing|partial)(?:; {PRIORITY})?|{PRIORITY})\)_")


def update_line(line: str, todo: dict[str, Any], project: Project) -> str:
    """Refresh checkbox, summary and state marker of an existing line; keep hand-written
    annotations after the uid and the description lines below it untouched."""
    m = MANAGED.match(line)
    assert m
    indent = m.group("indent")
    box, state = checkbox_and_state(todo)
    tail = line[m.end():]  # after the closing backtick of `todo:<uid>`
    tail = STATE.sub("", tail).rstrip()
    if state:
        tail += f" {state}"
    # end if
    return f"{indent}- [{box}] {clean_summary(todo, project)} — `todo:{m.group('uid')}`{tail}"
# end def


def render_tree(todos: list[dict[str, Any]], project: Project) -> dict[str, list[str]]:
    """uid -> its own lines (todo + description), without children."""
    return {t["uid"]: render(t, project) for t in todos}
# end def


# --------------------------------------------------------------------------- merge

MANAGED = re.compile(r"^(?P<indent>\s*)- \[.\] .* — `todo:(?P<uid>[0-9A-Za-z-]+)`")


def block_end(lines: list[str], start: int) -> int:
    """Index after the managed line at `start`: its `>` description lines only."""
    indent = len(MANAGED.match(lines[start]).group("indent"))  # type: ignore[union-attr]
    desc = " " * (indent + 2) + ">"
    i = start + 1
    while i < len(lines) and lines[i].startswith(desc):
        i += 1
    # end while
    return i
# end def


def subtree_end(lines: list[str], start: int) -> int:
    indent = len(MANAGED.match(lines[start]).group("indent"))  # type: ignore[union-attr]
    i = block_end(lines, start)
    while i < len(lines):
        if not lines[i].strip():
            break
        # end if
        if len(lines[i]) - len(lines[i].lstrip()) <= indent:
            break
        # end if
        i += 1
    # end while
    return i
# end def


def render_template(template: str, project: Project, calendar_id: int) -> str:
    """Fill the `{{project}}`, `{{calendar_id}}` and `{{script}}` (path to this script from the project root) placeholders."""
    script = os.path.relpath(Path(os.path.abspath(__file__)), project.root())
    return template.replace("{{project}}", project.name).replace("{{calendar_id}}", str(calendar_id)).replace("{{script}}", script)
# end def


def new_todo_file_text(project: Project, calendar_id: int) -> str:
    """The text of a todo file that does not exist yet: the template, or just the heading without one."""
    if not TEMPLATE_PATH.exists():
        return OLD_TEMPLATE_HEADER + "\n\n"
    # end if
    return render_template(TEMPLATE_PATH.read_text(encoding="utf-8"), project, calendar_id)
# end def


def upgrade_old_template(text: str, new_template: str) -> str:
    """Replace the bare header this script used to write (`# Todos`, blank, then the synced section) with `new_template`.

    Only the tail of the file counts: whatever is above the last `# Todos` line stays on top, the managed section below it is kept
    (its heading is renamed to the current one). A file that already has the new template's `## For Agents`, or whose last `# Todos`
    is followed by anything else than blanks and the synced section, is returned unchanged, so this is a no-op the second time.
    """
    lines = text.split("\n")
    if NEW_TEMPLATE_MARKER in lines:
        return text
    # end if
    starts = [i for i, line in enumerate(lines) if line.rstrip() == OLD_TEMPLATE_HEADER]
    if not starts:
        return text
    # end if
    start = starts[-1]
    rest = lines[start + 1:]
    first = next((i for i, line in enumerate(rest) if line.strip()), None)
    if first is not None and rest[first].rstrip() not in (SECTION, LEGACY_SECTION):
        vlog(f"`{OLD_TEMPLATE_HEADER}` is followed by something else, not the old template, left alone")
        return text
    # end if
    head = new_template.rstrip("\n").split("\n")
    manual = lines[:start]
    while manual and not manual[-1].strip():
        manual.pop()
    # end while
    prefix = manual + [""] if manual else []
    if first is None:
        return "\n".join(prefix + head) + "\n\n"
    # end if
    # the template ends with the section heading, the old block brings its own heading and managed lines
    if head and head[-1].rstrip() == SECTION:
        head.pop()
    # end if
    return "\n".join(prefix + head + [SECTION] + rest[first + 1:])
# end def


def refresh_description(
    lines: list[str], start: int, end: int, todo: dict[str, Any], project: Project, indent: int, report: list[str],
) -> int:
    """Bring the `>` description lines of the managed line at `start` up to CalDAV's text; returns the new block end.

    A block that contains CalDAV's text as it is, with or without notes written above or below it, stays as it is.
    Any other block means the description was edited on CalDAV and is replaced; lines that are gone are reported,
    never dropped silently. (CalDAV removing the whole description counts as notes: an empty text is in everything.)"""
    rendered = render(todo, project, indent)[1:]
    block = lines[start + 1:end]
    if any(block[at:at + len(rendered)] == rendered for at in range(len(block) - len(rendered) + 1)):
        return end
    # end if
    dropped = [line.strip().removeprefix(">").strip() for line in block if line not in rendered]
    vlog(f"{short(todo['uid'])}: description differs, replaced\n      file:    {block}\n      CalDAV:  {rendered}")
    lines[start + 1:end] = rendered
    report.append(f"description changed on CalDAV: {todo['uid']}")
    report += [f"  dropped: {line}" for line in dropped if line]
    return start + 1 + len(rendered)
# end def


def merge(text: str, todos: list[dict[str, Any]], project: Project, include_completed: bool = False) -> tuple[str, list[str]]:
    """Merge `todos` into the markdown `text`. Returns (new text, report lines)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    # end if
    report: list[str] = []
    mine = {t["uid"]: t for t in todos}

    # update existing, remember local ticks that CalDAV does not know
    i = 0
    seen: set[str] = set()
    while i < len(lines):
        m = MANAGED.match(lines[i])
        if not m:
            i += 1
            continue
        # end if
        uid, indent = m.group("uid"), len(m.group("indent"))
        end = block_end(lines, i)
        if uid in mine:
            if lines[i][indent:].startswith("- [x]") and mine[uid].get("status") != "COMPLETED":
                report.append(f"local tick not on CalDAV (not pushed): {uid}")
            # end if
            updated = update_line(lines[i], mine[uid], project)
            if updated == lines[i]:
                vlog(f"{short(uid)}: unchanged")
            else:
                vlog(f"{short(uid)}: line differs\n      file:    {lines[i]}\n      CalDAV:  {updated}")
            # end if
            lines[i] = updated
            end = refresh_description(lines, i, end, mine[uid], project, indent, report)
            seen.add(uid)
            i = end
        else:
            vlog(f"{short(uid)}: in file, not assigned to {project.name} (left alone)")
            i = end
        # end if
    # end while

    # new todos: under their parent if it is in the file, else in the managed section
    # (completed ones that are not in the file yet are ignored unless `include_completed`)
    new_todos = [
        t for t in todos
        if t["uid"] not in seen and not has_uid(lines, t["uid"])
        and (include_completed or t.get("status") != "COMPLETED")
    ]
    new_todos.sort(key=lambda t: (not t.get("created"), t.get("created") or ""))  # oldest first, undated last
    for t in todos:
        if t["uid"] not in seen and t not in new_todos and not has_uid(lines, t["uid"]):
            vlog(f"{short(t['uid'])}: completed and not in the file, ignored (--include-completed adds it)")
        # end if
    # end for
    pending = list(new_todos)
    progressed = True
    while pending and progressed:
        progressed = False
        for t in list(pending):
            parent = t.get("parent_uid")
            idx = find_uid(lines, parent) if parent else None
            if idx is None:
                continue
            # end if
            indent = len(MANAGED.match(lines[idx]).group("indent")) + 2  # type: ignore[union-attr]
            at = subtree_end(lines, idx)
            lines[at:at] = render(t, project, indent)
            report.append(f"added {t['uid']}")
            pending.remove(t)
            progressed = True
        # end for
    # end while
    roots = [t for t in pending]
    if roots:
        if SECTION not in lines and LEGACY_SECTION not in lines:
            if lines and lines[-1].strip():
                lines.append("")
            # end if
            lines += [SECTION, ""]
        # end if
        pos = len(lines)
        in_pending = {t["uid"] for t in roots}
        for t in roots:
            if (t.get("parent_uid") or "") in in_pending:
                continue  # emitted below its parent
            # end if
            block = with_children(t, roots, project, 0)
            lines[pos:pos] = block
            pos += len(block)
            report.append(f"added {t['uid']}")
        # end for
        for t in roots:
            if (t.get("parent_uid") or "") in in_pending:
                report.append(f"added {t['uid']}")
            # end if
        # end for
    # end if
    return "\n".join(lines) + "\n", report
# end def


def purge(text: str, matches: set[str], label: str) -> tuple[str, list[str]]:
    """Remove every managed line (with its description and children) whose uid, and the uid of
    every managed line below it, is in `matches`. A parent with a child that is not stays."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    # end if
    report: list[str] = []
    i = 0
    while i < len(lines):
        m = MANAGED.match(lines[i])
        if not m or m.group("uid") not in matches:
            i += 1
            continue
        # end if
        stop = subtree_end(lines, i)
        subtree = [x.group("uid") for x in map(MANAGED.match, lines[i:stop]) if x]
        if all(u in matches for u in subtree):
            report.extend(f"{label} {u}" for u in subtree)
            del lines[i:stop]
        else:
            kept = [u for u in subtree if u not in matches]
            vlog(f"{short(m.group('uid'))}: matches, but kept because of " + ", ".join(short(u) for u in kept))
            i += 1
        # end if
    # end while
    return "\n".join(lines) + "\n", report
# end def


def purge_missing(text: str, all_uids: set[str]) -> tuple[str, list[str]]:
    """Drop todos that no longer exist on CalDAV at all."""
    managed = {m.group("uid") for m in map(MANAGED.match, text.split("\n")) if m}
    vlog(f"{len(managed)} managed lines, {len(managed & all_uids)} still on CalDAV, {len(managed - all_uids)} missing")
    return purge(text, managed - all_uids, "purged missing")
# end def


def purge_complete(text: str, done_uids: set[str]) -> tuple[str, list[str]]:
    """Drop todos that are completed on CalDAV."""
    managed = {m.group("uid") for m in map(MANAGED.match, text.split("\n")) if m}
    vlog(f"{len(managed)} managed lines, {len(managed & done_uids)} completed on CalDAV")
    return purge(text, done_uids, "purged completed")
# end def


def with_children(todo: dict[str, Any], pool: list[dict[str, Any]], project: Project, indent: int) -> list[str]:
    out = render(todo, project, indent)
    for child in pool:
        if child.get("parent_uid") == todo["uid"]:
            out += with_children(child, pool, project, indent + 2)
        # end if
    # end for
    return out
# end def


def find_uid(lines: list[str], uid: str | None) -> int | None:
    for i, line in enumerate(lines):
        m = MANAGED.match(line)
        if m and m.group("uid") == uid:
            return i
        # end if
    # end for
    return None
# end def


def has_uid(lines: list[str], uid: str) -> bool:
    return find_uid(lines, uid) is not None
# end def


# --------------------------------------------------------------------------- MCP

def parse_result(result: Any) -> list[dict[str, Any]]:
    data = getattr(result, "structuredContent", None)
    if data is None:
        # FastMCP puts each list item into its own text block
        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        data = [json.loads(t) for t in texts]
        if len(data) == 1 and isinstance(data[0], list):
            data = data[0]
        # end if
    # end if
    if isinstance(data, dict):
        data = data.get("result", data)
    # end if
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected list_todos result: {str(data)[:200]}")
    # end if
    return data
# end def


PAGE_SIZE = 50


async def collect_pages(call_page: Any, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """
    Reads `list_todos` page by page, as one response must stay below the MCP client's 1 MiB limit per event.
    A short page is the last one; a page that brings nothing new (a server without paging sends everything again) ends it too.
    """
    todos: list[dict[str, Any]] = []
    seen: set[str] = set()
    while True:
        page = await call_page(len(todos), page_size)
        new = [todo for todo in page if todo.get("uid") not in seen]
        seen.update(todo.get("uid") for todo in new)
        todos.extend(new)
        if len(page) < page_size or not new:
            return todos
        # end if
    # end while
# end def


async def fetch_todos(url: str, token: str, calendar_id: int) -> list[dict[str, Any]]:
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async with create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}) as http:
        async with streamable_http_client(url, http_client=http) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            async def call_page(offset: int, limit: int) -> list[dict[str, Any]]:
                result = await session.call_tool("list_todos", {"calendar_id": calendar_id, "offset": offset, "limit": limit})
                if getattr(result, "isError", False):
                    raise RuntimeError(f"list_todos failed: {result.content}")
                # end if
                return parse_result(result)
            # end def

            return await collect_pages(call_page)
        # end with
    # end with
# end def


# --------------------------------------------------------------------------- main

def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        # end with
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
# end def


LINE = re.compile(r"^(?P<indent>\s*)- \[(?P<box>.)\] (?P<summary>.*?) — `todo:(?P<uid>[0-9A-Za-z-]+)`(?P<tail>.*)$")
STATE_TEXT = re.compile(rf"_\((?:(?P<state>done|cancelled|needs action|in process[^;)]*|missing|partial)(?:; )?)?(?P<prio>{PRIORITY})?\)_")
MAX_DETAIL_LINES = 30


def managed_todos(text: str) -> dict[str, dict[str, Any]]:
    """uid -> where it stands (`parent / child` path), checkbox, summary, state marker and `>` description rows; file order."""
    lines = text.split("\n")
    found: dict[str, dict[str, Any]] = {}
    stack: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if not m:
            continue
        # end if
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        # end while
        stack.append((indent, m.group("summary"), m.group("box")))
        rows: list[str] = []
        prefix = " " * (indent + 2) + ">"
        j = i + 1
        while j < len(lines) and lines[j].startswith(prefix):
            rows.append(lines[j].strip())
            j += 1
        # end while
        state = STATE_TEXT.search(m.group("tail"))
        found[m.group("uid")] = {
            "path": " / ".join(summary for _, summary, _ in stack), "box": m.group("box"), "summary": m.group("summary"),
            "shown": " / ".join(struck(summary, box) for _, summary, box in stack),
            "state": (state.group("state") or "") if state else "", "prio": (state.group("prio") or "") if state else "",
            "rows": rows,
        }
    # end for
    return found
# end def


def struck(text: str, box: str) -> str:
    """The text with a strikethrough if the checkbox says cancelled."""
    return f"~~{text}~~" if box == "-" else text
# end def


def describe_changes(old: str, new: str) -> list[str]:
    """What a stage did to the managed todos of a file, one short line per change, for the body of the commit message."""
    before, after = managed_todos(old), managed_todos(new)
    lines: list[str] = []
    for uid, now in after.items():
        was = before.get(uid)
        if was is None:
            lines.append(f"added: {now['shown']}" + (" (cancelled)" if now["box"] == "-" else ""))
            continue
        # end if
        if was["box"] != now["box"]:
            if now["box"] == "x":
                lines.append(f"ticked: {now['shown']}")
            elif now["box"] == "-":
                lines.append(f"cancelled: {now['shown']}")
            elif was["box"] == "x":
                lines.append(f"unticked: {now['shown']}")
            elif was["box"] == "-" and now["box"] == " ":
                lines.append(f"reopened: {now['shown']}")
            else:
                lines.append(f"checkbox [{was['box']}] -> [{now['box']}]: {now['shown']}")
            # end if
        elif was["state"] != now["state"]:
            lines.append(f"state: {now['shown']} ({was['state'] or 'none'} -> {now['state'] or 'none'})")
        # end if
        if was["prio"] != now["prio"]:
            lines.append(f"priority: {now['shown']} ({was['prio'] or 'none'} -> {now['prio'] or 'none'})")
        # end if
        if was["summary"] != now["summary"]:
            lines.append(f"renamed: {struck(was['summary'], was['box'])} -> {struck(now['summary'], now['box'])}")
        # end if
        if was["rows"] != now["rows"]:
            lines.append(f"description changed: {now['shown']}")
        # end if
    # end for
    for uid, was in before.items():
        if uid not in after:
            lines.append(f"removed: {was['shown']}")
        # end if
    # end for
    return lines
# end def


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
# end def


def todo_dir_usable(project: Project) -> bool:
    """The todo file's folder exists, or can be created because the project root exists inside a git work tree
    (the folder is made when the file is written, so `--dry-run` creates nothing)."""
    folder = project.file().parent
    if folder.is_dir():
        return True
    # end if
    if not project.root().is_dir():
        print(f"[{project.name}] skipped, {project.root()} does not exist", file=sys.stderr)
        return False
    # end if
    if git(project.root(), "rev-parse", "--show-toplevel").returncode != 0:
        print(f"[{project.name}] skipped, {folder} does not exist and {project.root()} is not in a git repo", file=sys.stderr)
        return False
    # end if
    vlog(f"{project.name}: {folder} does not exist, will create it")
    return True
# end def


def amendable(top: Path, subject: str, files: list[str]) -> bool:
    """`HEAD` is a clean todo commit that may be rewritten: exactly this `subject`, touching only `files`,
    on no remote branch, and no merge, rebase, cherry-pick or revert is running."""
    if git(top, "log", "-1", "--format=%s", "HEAD").stdout.strip() != subject:
        return False
    # end if
    touched = git(top, "show", "-z", "--name-only", "--format=", "HEAD").stdout.split("\0")  # -z: no quoting of paths like `ai/°base/…`
    if not {t for t in touched if t} <= set(files):
        return False
    # end if
    if git(top, "branch", "-r", "--contains", "HEAD").stdout.strip():
        return False
    # end if
    git_dir = Path(git(top, "rev-parse", "--absolute-git-dir").stdout.strip())
    return not any((git_dir / marker).exists() for marker in (
        "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply",
    ))
# end def


def commit_written(
    written: list[tuple[Project, Path]], default_prefix: str = "", action: str = "synced todos",
    details: dict[str, list[str]] | None = None, amend: bool = True,
) -> None:
    """Commit in the git root that contains each project (found from the project's own directory,
    so a subfolder of a monorepo commits in the monorepo root). One commit per (repo, prefix),
    limited to the written files, so other staged changes stay out."""
    groups: dict[tuple[str, str], list[tuple[Project, Path]]] = {}
    for project, path in written:
        top = git(path.parent, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            print(f"[{project.name}] not a git repo, not committing", file=sys.stderr)
            continue
        # end if
        prefix = project.commit_prefix if project.commit_prefix is not None else default_prefix
        vlog(f"{project.name}: git root {top.stdout.strip()}, prefix {prefix!r}")
        groups.setdefault((top.stdout.strip(), prefix), []).append((project, path))
    # end for
    for (top, prefix), items in groups.items():
        files = [str(path.resolve().relative_to(Path(top).resolve())) for _, path in items]
        names = ", ".join(dict.fromkeys(project.name for project, _ in items))
        added = git(Path(top), "add", "--", *files)
        if added.returncode != 0:
            print(f"[{names}] git add failed: {added.stderr.strip()}", file=sys.stderr)
            continue
        # end if
        if git(Path(top), "diff", "--cached", "--quiet", "--", *files).returncode == 0:
            vlog(f"{names}: nothing staged in {top} (ignored or unchanged in git), no commit")
            continue
        # end if
        several = len({project.name for project, _ in items}) > 1
        body = [
            f"- {f'[{project.name}] ' if several else ''}{line}"
            for project, _ in items for line in (details or {}).get(project.name, [])
        ]
        if len(body) > MAX_DETAIL_LINES:
            body = body[:MAX_DETAIL_LINES] + [f"- ... and {len(body) - MAX_DETAIL_LINES} more"]
        # end if
        subject = f"{prefix}[TODOs] {action} for {names}."
        amending = amend and action == "synced todos" and amendable(Path(top), subject, files)
        if amending:
            old = git(Path(top), "log", "-1", "--format=%b", "HEAD").stdout.strip()
            body = [line for line in old.split("\n") if line] + body
            if len(body) > MAX_DETAIL_LINES:
                body = body[:MAX_DETAIL_LINES] + [f"- ... and {len(body) - MAX_DETAIL_LINES} more"]
            # end if
        # end if
        message = ["-m", subject] + (["-m", "\n".join(body)] if body else [])
        done = git(Path(top), "commit", *(["--amend"] if amending else []), *message, "--", *files)
        if done.returncode != 0:
            print(f"[{names}] git commit failed: {done.stderr.strip() or done.stdout.strip()}", file=sys.stderr)
        else:
            head = git(Path(top), "rev-parse", "--short=9", "HEAD").stdout.strip()
            print(f"[{names}] {'amended' if amending else 'committed'} {head} in {top}: {subject}")
        # end if
    # end for
# end def


KEPT_LINE = re.compile(r"^\s*[-*•]\s+\[[^\]\n]?\](?:\s|$)")
QUOTE_ROW = re.compile(r"^\s*>")


def reset_text(text: str, template: str) -> tuple[str, list[str]]:
    """The template followed by the todo-like lines of `text`; everything else is dropped (and reported).

    Todo-like: a checkbox line (`-`, `*` or `•`, then `[` any single character `]`, any indentation) and the
    `>` rows that directly follow it. The kept lines stay in their order, with their indentation."""
    kept: list[str] = []
    report: list[str] = []
    after_kept = False
    for line in text.split("\n"):
        if KEPT_LINE.match(line) or (after_kept and QUOTE_ROW.match(line)):
            kept.append(line)
            after_kept = True
            continue
        # end if
        after_kept = False
        if line.strip():
            report.append(f"dropped: {line.strip()}")
        # end if
    # end for
    return template.rstrip("\n") + "\n\n" + ("\n".join(kept) + "\n" if kept else ""), report
# end def


def reset_stage(text: str, project: Project, calendar_id: int) -> tuple[str, list[str]]:
    """Stage of `sync` for `--reset-todo-file`: see `reset_text`."""
    return reset_text(text, new_todo_file_text(project, calendar_id))
# end def


def assert_resettable(project: Project) -> None:
    """A reset throws text away, so the file must be in git with nothing uncommitted (the commit is the way back)."""
    path = project.file()
    if not project.todo_file.endswith(".md"):
        raise ValueError(f"[{project.name}] --reset-todo-file only works on markdown files, not {path.name}")
    # end if
    if not path.exists():
        return
    # end if
    if git(path.parent, "rev-parse", "--show-toplevel").returncode != 0:
        raise ValueError(f"[{project.name}] {path} is not in a git repository, a reset could not be undone")
    # end if
    if git(path.parent, "check-ignore", "-q", "--", str(path)).returncode == 0:
        raise ValueError(f"[{project.name}] {path} is ignored by git, a reset could not be undone")
    # end if
    if git(path.parent, "status", "--porcelain", "--", str(path)).stdout.strip():
        raise ValueError(f"[{project.name}] {path} has uncommitted changes, commit or stash them before resetting it")
    # end if
# end def


def upgrade_stage(text: str, project: Project, calendar_id: int) -> tuple[str, list[str]]:
    """Stage of `sync`: markdown todo files with the old bare header get the template (see `upgrade_old_template`)."""
    if not project.todo_file.endswith(".md"):
        return text, []
    # end if
    new = upgrade_old_template(text, new_todo_file_text(project, calendar_id))
    return new, ["upgraded the old header to the template"] if new != text else []
# end def


def select_projects(config: Config, only: str | None) -> list[Project]:
    """All projects, or the one whose name or one of whose tags is `only` (ignoring case)."""
    if not only:
        return list(config.projects)
    # end if
    found = [p for p in config.projects if only.casefold() in {p.name.casefold(), *(t.casefold() for t in p.tags)}]
    if not found:
        raise ValueError(f"no project {only!r} (known: {', '.join(p.name for p in config.projects)})")
    # end if
    return found
# end def


def sync(
    config: Config,
    todos: list[dict[str, Any]],
    only: str | None,
    dry_run: bool,
    use_git: bool = True,
    purge_missing_: bool = False,
    purge_complete_: bool = False,
    include_completed: bool = False,
    reset_todo_file: bool = False,
    add_files: bool = False,
    amend: bool = True,
) -> int:
    """Sync, then (optionally) purge missing, then purge completed: each stage is written and
    committed on its own, so the history shows what was a sync and what was a cleanup."""
    if reset_todo_file and not only:
        raise ValueError("--reset-todo-file needs --project: it rebuilds one file")
    # end if
    if reset_todo_file and not use_git:
        raise ValueError("--reset-todo-file needs git (the commit is the only way back), drop --no-git")
    # end if
    assigned = assign(todos, config.projects)  # all projects take part, so a tag never falls through to another one
    all_uids = {t["uid"] for t in todos}
    done_uids = {t["uid"] for t in todos if t.get("status") == "COMPLETED"}
    stages: list[tuple[str, Any]] = []
    if reset_todo_file:
        stages.append(("reset todo file", lambda text, project: reset_stage(text, project, config.calendar_id)))
    # end if
    if TEMPLATE_PATH.exists():
        stages.append(("upgraded todo file header", lambda text, project: upgrade_stage(text, project, config.calendar_id)))
    # end if
    stages += [
        ("synced todos", lambda text, project: merge(text, assigned[project.name], project, include_completed)),
    ]
    if purge_missing_:
        stages.append(("purged missing todos", lambda text, project: purge_missing(text, all_uids)))
    # end if
    if purge_complete_:
        stages.append(("purged completed todos", lambda text, project: purge_complete(text, done_uids)))
    # end if

    projects = select_projects(config, only)
    for p in projects:
        if p.path is None:
            print(f"[{p.name}] skipped, no path in {LOCAL_CONFIG.name} ({len(assigned[p.name])} todos not written)", file=sys.stderr)
        # end if
    # end for
    if projects and all(p.path is None for p in projects):
        print(
            f"No project has a path, so nothing was written. Add this repository (and/or its subprojects) to {REPO_CONFIG} under \"projects\", "
            f"e.g. \"{projects[0].name}\": {{\"path\": \".\"}}, or give them a path in {LOCAL_CONFIG.name}.",
            file=sys.stderr,
        )
    # end if
    projects = [p for p in projects if p.path is not None and todo_dir_usable(p)]
    if reset_todo_file and not dry_run:
        for project in projects:
            assert_resettable(project)
        # end for
    # end if
    originals = {
        p.name: p.file().read_text(encoding="utf-8") if p.file().exists() else new_todo_file_text(p, config.calendar_id) for p in projects
    }
    current = dict(originals)
    changed: set[str] = set()
    for action, stage in stages:
        written: list[tuple[Project, Path]] = []
        details: dict[str, list[str]] = {}
        LINKED.clear()
        for project in projects:
            new, report = stage(current[project.name], project)
            for line in report:
                print(f"[{project.name}] {line}")
            # end for
            if new == current[project.name]:
                if action == "synced todos":
                    print(f"[{project.name}] up to date ({len(assigned[project.name])} todos, {count_open(assigned[project.name])} open)")
                # end if
                continue
            # end if
            details[project.name] = describe_changes(current[project.name], new)
            current[project.name] = new
            changed.add(project.name)
            if not dry_run:
                project.file().parent.mkdir(parents=True, exist_ok=True)
                write_atomic(project.file(), new)
                written.append((project, project.file()))
                print(f"[{project.name}] wrote {project.file()} ({action})")
            # end if
        # end for
        if use_git and written:
            commit_written(written, config.commit_prefix, action, details, amend)
        # end if
        if add_files and use_git and not dry_run and action == "synced todos":
            for project in projects:
                commit_mentions(project)
            # end for
        # end if
    # end for
    if dry_run:
        for project in projects:
            sys.stdout.writelines(difflib.unified_diff(
                originals[project.name].splitlines(True), current[project.name].splitlines(True),
                str(project.file()), str(project.file()),
            ))
        # end for
    # end if
    return len(changed)
# end def


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="tracked tag to project mapping")
    ap.add_argument("--local-config", type=Path, default=LOCAL_CONFIG, help="machine-local project paths (gitignored)")
    ap.add_argument("--repo-config", type=Path, default=REPO_CONFIG, help="committed per-repository settings, layered between the tracked and the local config")
    ap.add_argument("--migrate-local-paths", action="store_true", help="move the local project paths that lie inside this repository (and their commit prefixes) into the repo config, committing it; the local ones become null")
    ap.add_argument("--project", help="only this project (its name or one of its tags)")
    ap.add_argument("--dry-run", action="store_true", help="print a diff, write nothing")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every comparison (assignment, line diffs, purge decisions)")
    ap.add_argument("--no-git", action="store_true", help="do not commit the written files")
    ap.add_argument("--purge-missing", action="store_true", help="drop managed lines whose todo no longer exists on CalDAV (own commit)")
    ap.add_argument("--purge-complete", "--purge-completed", action="store_true", help="drop todos that are completed on CalDAV (own commit); a parent stays while a child is open")
    ap.add_argument("--include-completed", "--include-complete", action="store_true", help="also add completed todos that are not in the file yet (ignored by default)")
    ap.add_argument("--reset-todo-file", action="store_true", help="rebuild the todo file of --project from the template plus its todo lines (checkbox lines and their `>` rows), everything else is dropped; refuses while the file has uncommitted changes; own commit, then the normal sync")
    ap.add_argument("--add-files", "--add", action="store_true", help="also stage and commit the files the todos mention (those with changes, each on its own); without it they are only linked")
    ap.add_argument("--no-amend", action="store_true", help="always make a new commit, even if HEAD is an unpushed todo sync commit of the same projects that could take the changes")
    ap.add_argument("--write-schema", action="store_true", help=f"write {SCHEMA_PATH.name}, {LOCAL_SCHEMA_PATH.name} and {REPO_SCHEMA_PATH.name} and exit")
    return ap
# end def


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    global VERBOSE
    VERBOSE = args.verbose

    for schema_path, text in ((SCHEMA_PATH, schema_text()), (LOCAL_SCHEMA_PATH, local_schema_text()), (REPO_SCHEMA_PATH, repo_schema_text())):
        if args.write_schema or not schema_path.exists() or schema_path.read_text() != text:
            schema_path.write_text(text)
            if args.write_schema:
                print(f"wrote {schema_path}")
            # end if
        # end if
    # end for
    if args.write_schema:
        return 0
    # end if

    try:
        config = load_config(args.config, args.local_config, repo=args.repo_config)
        ensure_repo_file(args.repo_config, repo_prefix(config), args.dry_run, not args.no_git)
        if args.migrate_local_paths:
            only = {p.name for p in select_projects(config, args.project)}
            if migrate_local_paths(config, args.repo_config, args.local_config, only, args.dry_run, not args.no_git) and not args.dry_run:
                config = load_config(args.config, args.local_config, repo=args.repo_config)
            # end if
        # end if
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if config.env_file:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / config.env_file)
    # end if
    url, token = os.environ.get(config.url_env), os.environ.get(config.token_env)
    if not url or not token:
        print(f"{config.url_env} / {config.token_env} not set (looked in env and {config.env_file})", file=sys.stderr)
        return 2
    # end if
    todos = asyncio.run(fetch_todos(url, token, config.calendar_id))
    try:
        sync(config, todos, args.project, args.dry_run, not args.no_git, args.purge_missing, args.purge_complete, args.include_completed, args.reset_todo_file, args.add_files, not args.no_amend)
        selected = {p.name for p in select_projects(config, args.project)}
        moves = {} if args.migrate_local_paths else {name: path for name, path in movable(config, args.repo_config).items() if name in selected}
        for line in add_to_repo_hint(config, moves, args.config, args.repo_config, args.local_config):
            print(line, file=sys.stderr)
        # end for
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    return 0
# end def


if __name__ == "__main__":
    sys.exit(main())
# end if
