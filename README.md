# gh-fetcher

Clone and manage GitHub repositories in a structured source folder (`~/src/owner/repo`).

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
| `GH_SYNC_EXCLUDE` | Comma-separated folder names to skip during sync | — |

## Usage

```bash
# Clone a repo (HTTPS) into ~/src/owner/repo
./gh-fetcher.py clone owner/repo

# Clone via SSH
./gh-fetcher.py clone owner/repo --ssh

# Override source directory
./gh-fetcher.py --dir ~/code clone owner/repo

# Accepts full URLs
./gh-fetcher.py clone https://github.com/owner/repo
./gh-fetcher.py clone git@github.com:owner/repo.git

# If the repo already exists locally, it pulls instead
./gh-fetcher.py clone owner/repo

# Your own repos automatically clone via SSH (based on GH_USER)
./gh-fetcher.py clone yourname/repo

# Fork to your account, clone your fork via SSH, add upstream remote
./gh-fetcher.py clone owner/repo --fork
```

## Sync

Pull all repos in your source folder. Forks are automatically synced with upstream.

```bash
# Sync everything
./gh-fetcher.py sync

# Exclude folders (adds to GH_SYNC_EXCLUDE)
./gh-fetcher.py sync --exclude "archive,old projects"
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
