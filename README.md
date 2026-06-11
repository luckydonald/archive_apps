# base

Small reusable git base for other repositories.

This history is intentionally rooted at `empty/init` from `https://github.com/EmptyAAS/empty.git`. That gives multiple repos the same empty ancestor commit, which makes it possible to rebase or merge this base into another repo in a predictable way.

## Table of contents

<!-- TOC -->
* [base](#base)
  * [Table of contents](#table-of-contents)
* [Add This To Your Repo](#add-this-to-your-repo)
  * [Overview](#overview)
    * [Which Workflow To Choose](#which-workflow-to-choose)
* [Installation](#installation)
  * [Setup](#setup)
          * [Shared initial commit](#shared-initial-commit)
  * [Setup: a) Checkout](#setup-a-checkout)
      * [Rename branch](#rename-branch)
        * [Local branch](#local-branch)
        * [Remote branch](#remote-branch)
          * [Hosted Git](#hosted-git)
  * [Setup: b) Rebase Onto `base/base`](#setup-b-rebase-onto-basebase)
  * [Setup: c) Merge `base/base`](#setup-c-merge-basebase)
    * [All code for c) as a single copy pastable one:](#all-code-for-c-as-a-single-copy-pastable-one)
  * [After Adopting The Base](#after-adopting-the-base)
    * [Git LFS](#git-lfs)
    * [Monorepo subfolders: per-subfolder `.claude/`](#monorepo-subfolders-per-subfolder-claude)
<!-- TOC -->

# Add This To Your Repo

## Overview
There are three ways to adopt this:

- start with it from the get-go, creating your branch from `base/base`.
  - obviously only works if you haven't commited anything yet.
  - otherwise see rebase below, that's basically _"plz pretend I started from that and did all my own commits afterward!"_
- rebase your repo on top of `base/base` if you want this base to become part of your linear history 
  - recommended if your git is not yet used by others
- merge `base/base` into your repo if you do not want to rewrite history

If you only want a one-time copy of the files, just copy them manually. The steps below are for keeping your repo connected to this base over time.

### Which Workflow To Choose

Choose checkout if:
- you want to create a new project
- or have not commited anything yet

Choose rebase if:

- you want this base to sit underneath your repo's commits
- you prefer a linear history
- force-pushing rewritten history is acceptable

Choose merge if:

- your branch is already published or shared
- you want the least disruptive adoption path
- you are fine with explicit merge commits for base updates


# Installation
## Setup

Add the remotes you need, as below.
We assume your username would be `luckydonald` on GitHub, otherwise remove the `luckydonald@` part from the repository URLs, or replace with your own.
Specifying the username is only needed if you have more than one GitHub account configured on your machine (e.g. private and work).

```bash
git remote add base https://luckydonald@github.com/luckydonald/base.git
git fetch base base
git lfs install
pre-commit install
```

###### Shared initial commit
> > ℹ️  
> > If your repository does not already descend from `empty/init`, and you want to merge cleanly later, and it's okay to rewrite its history, re-root it once:
> 
> 1. ```bash
>    git remote add empty https://luckydonald@github.com/EmptyAAS/empty.git
>    git fetch empty init
>    ```
> 2. ```bash
>    git rebase --root --onto empty/init
>    ```
>
> That keeps your file history intact, but rewrites every commit in the branch so the new root is the shared empty commit.

## Setup: a) Checkout

Use this if you are starting fresh and want your repository branch to begin at `base/base`.

This is the simplest option, but it only makes sense before you have your own commits on the branch.

We assume you want to give your branch the name `mane` here. Replace in the commands below as needed.

Initial adoption:

```bash
git switch --create mane base/base
```

If your git version is older and does not support `switch`, use:

```bash
git checkout -b mane base/base
```

Then point your own repository remote at the branch and publish it as usual:

```bash
git push -u origin mane
```

Future updates work the same as in the other setups: fetch `base`, then either rebase onto `base/base` or merge `base/base`, depending on the workflow you chose for ongoing maintenance.

Notes:

- replace `main` with whatever branch name your repo should use
- this avoids the one-time re-rooting and adoption steps from the rebase and merge workflows
- once you start adding your own commits, updates from this base are handled with either section `b)` or `c)`

#### Rename branch
In case you ran above commands, you'd get the `main` branch. If you want to rename it after-the-fact, here's how:

> In this example I'll rename `main` to `mane` to make sure it's properly ponified.

##### Local branch
```shell
OLD_NAME=main
NEW_NAME=mane
REMOTE="origin"

git branch -m "${OLD_NAME}" "${NEW_NAME}"
git fetch "${REMOTE}"
git remote set-head "${REMOTE}" -a
```
##### Remote branch

###### Hosted Git
If your repo is on git hoster (GitHub, GitLab, Gitea, Forgejo, …) with a website to manage it,
it's better to rename the branch in the GUI there, as it will make sure that all settings references will be updated as well.
For example the protected branch settings, and default `git checkout` branch settings



## Setup: b) Rebase Onto `base/base`

Use this if you want a clean linear history, and you are comfortable rewriting your branch.

Initial adoption:

```bash
git rebase --onto base/base empty/init
```

After that, future updates are just:

```bash
git fetch base
git rebase base/base
```

Notes:

- resolve conflicts as they appear, then continue with `git rebase --continue`
- if you already pushed the branch, you will usually need `git push --force-with-lease`
- this is best for personal branches or repos where force-pushes are acceptable

## Setup: c) Merge `base/base`

Use this if you want to preserve existing history and avoid rebasing published branches.

Initial adoption into an unrelated existing repo:

```bash
git merge --allow-unrelated-histories --no-ff base/base
```

Future updates:

```bash
git fetch base
git merge --no-ff base/base
```

Notes:

- this keeps a merge commit for each base update
- this is the safer choice for shared branches
- if your repo already shares `empty/init` as an ancestor, the initial `--allow-unrelated-histories` is not needed

### All code for c) as a single copy pastable one:
```shell
git remote add empty https://luckydonald@github.com/EmptyAAS/empty.git
git remote add base https://luckydonald@github.com/luckydonald/base.git
git fetch empty init
git fetch base base
git lfs install
git merge --allow-unrelated-histories --no-verify empty/init
git merge --no-ff --no-verify base/base
pre-commit install
```
## After Adopting The Base

Once the base is present in your repo, the files provided by this repo live in your repo like normal files. In particular, the `scripts/°base/*` helpers are intended to be run from inside the consuming repository.

### Git LFS

This base tracks binary image files (`.png`, `.jpg`, `.jpeg`) with [Git LFS](https://git-lfs.com). The `git lfs install` command in the setup steps above is a one-time setup per machine. The `.gitattributes` file already defines which file types are tracked, so no additional `git lfs track` calls are needed.

After the base files are present in a repository, `scripts/°base/init/checkout.sh` also installs the local LFS hooks and disables GitHub LFS lock verification for discovered GitHub HTTPS remotes. This avoids push failures like `You must have push access to verify locks` in repos that use LFS files but do not use LFS locks.

### Monorepo subfolders: per-subfolder `.claude/`

If you've merged `base` at the top of a monorepo but intend to run Claude from a subfolder (e.g. `monorepo/some_project/`), Claude Code's settings discovery starts at the launch directory and won't reach the root-level `.claude/` from there. Run the helper once inside each subfolder where you want Claude:

```bash
cd some_project
../scripts/°base/init/link-subproject-claude.sh
```

This creates a relative symlink `some_project/.claude → ../.claude`, so the same `.claude/settings.json` and `.claude/hooks/permission-check.py` apply. The hooks themselves locate `scripts/°base/` via `git rev-parse --show-toplevel`, so they work from any depth. AI artifacts then land under the subfolder — `some_project/ai/query.md`, `some_project/ai/plans/…` — while commits still go to the single monorepo git, with git-root-relative paths like `some_project/ai/query.md`.

The helper is idempotent (no-ops if the symlink already points at the right place), refuses to clobber a non-symlink `.claude/`, and exits cleanly at the git root, so it's safe to re-run or wire into your own setup script.
