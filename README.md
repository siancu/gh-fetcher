# gh-fetcher

Clone and manage GitHub/GitLab repositories in a structured source folder (`~/src/owner/repo` or `~/src/group/subgroup/project`).

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
# Copy and configure
cp .env.example .env
# Edit .env with your values
```

### Environment variables

| Variable | Description | Default |
|------------|--------------------------------------|---------|
| `GH_SRC_DIR` | Root folder for cloned repos | `~/src` |
| `GH_USER` | Your GitHub username (needed for `--fork`) | — |
| `GH_TOKEN` | GitHub personal access token (needed for `--fork`) | — |
| `GITLAB_HOST` | Self-hosted GitLab host for GitLab SSH clones | — |
| `GH_SYNC_EXCLUDE` | Comma-separated folder names to skip during sync | — |

## Usage

### GitHub

```bash
# Clone a repo (HTTPS) into ~/src/owner/repo
./gh-fetcher.py github clone owner/repo

# Clone via SSH
./gh-fetcher.py github clone owner/repo --ssh

# Override source directory
./gh-fetcher.py --dir ~/code github clone owner/repo

# Accepts full URLs
./gh-fetcher.py github clone https://github.com/owner/repo
./gh-fetcher.py github clone git@github.com:owner/repo.git

# If the repo already exists locally, it pulls instead
./gh-fetcher.py github clone owner/repo

# Your own repos automatically clone via SSH (based on GH_USER)
./gh-fetcher.py github clone yourname/repo

# Fork to your account, clone your fork via SSH, add upstream remote
./gh-fetcher.py github clone owner/repo --fork
```

### GitLab

GitLab clones always use SSH and require `GITLAB_HOST`.

```bash
GITLAB_HOST=gitlab.example.com

# Clone into ~/src/group/subgroup/project
./gh-fetcher.py gitlab clone group/subgroup/project

# Full self-hosted GitLab URLs also work
./gh-fetcher.py gitlab clone https://gitlab.example.com/group/subgroup/project
./gh-fetcher.py gitlab clone git@gitlab.example.com:group/subgroup/project.git
```

## Sync

Pull repos for the selected provider in your source folder. GitHub forks are automatically synced with upstream.

```bash
# Sync GitHub repos
./gh-fetcher.py github sync

# Sync GitLab repos
./gh-fetcher.py gitlab sync

# Exclude folders (adds to GH_SYNC_EXCLUDE)
./gh-fetcher.py github sync --exclude "archive,old projects"
```

### What sync does for each repo

1. **Skips** repos with uncommitted changes (with a warning)
2. **Pulls** from origin
3. If the repo has an `upstream` remote (i.e. it's a fork):
   - Fetches upstream
   - Fast-forward merges `upstream/<branch>` into current branch
   - Pushes the result to origin

### Excluding folders

Set `GH_SYNC_EXCLUDE` in `.env` to permanently exclude folders:

```
GH_SYNC_EXCLUDE=archive,old projects,experiments
```

Spaces in folder names work fine — entries are split on commas and trimmed.

The `--exclude` flag adds to the list for a single run.

## How `--fork` works

1. Forks `owner/repo` to `GH_USER/repo` via the GitHub API
2. Clones your fork via SSH into `<src_dir>/owner/repo`
3. Adds `upstream` remote pointing to the original repo
4. Fetches upstream
