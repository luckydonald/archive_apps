# scripts/°base/tests

Tests for the Python helpers in [`scripts/°base/`](/Users/user/Documents/programming/Python/base/scripts/°base).

The local project environment for these helpers lives in [`scripts/°base/pyproject.toml`](/Users/user/Documents/programming/Python/base/scripts/°base/pyproject.toml).

## Run the whole test folder

From the repository root:

```bash
uv run --project scripts/°base python -m unittest discover -s scripts/°base/tests -v
```

## Run only `git_remote_fix`

From the repository root:

```bash
uv run --project scripts/°base python -m unittest ai.scripts.tests.test_git_remote_fix -v
```

## Run the test file directly

From the repository root:

```bash
uv run --project scripts/°base python scripts/°base/tests/test_git_remote_fix.py
```

## Run the interactive helper

From the repository root:

```bash
uv run --project scripts/°base python scripts/°base/git/remote/fix_username.py
```

All commands assume `uv` will resolve dependencies from [`scripts/°base/pyproject.toml`](/Users/user/Documents/programming/Python/base/scripts/°base/pyproject.toml).
