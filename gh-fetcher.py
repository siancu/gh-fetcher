#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "python-dotenv"]
# ///

"""gh-fetcher: Clone and manage GitHub repositories in a structured source folder."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the script's directory
load_dotenv(Path(__file__).resolve().parent / ".env")

import requests


def parse_repo(input_str: str) -> tuple[str, str]:
    """Parse owner/repo from various input formats.

    Accepts:
        owner/repo
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        git@github.com:owner/repo.git
    """
    # Strip trailing slashes and .git suffix
    input_str = input_str.rstrip("/")
    if input_str.endswith(".git"):
        input_str = input_str[:-4]

    # Full HTTPS URL
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)$", input_str)
    if m:
        return m.group(1), m.group(2)

    # SSH URL
    m = re.match(r"git@github\.com:([^/]+)/([^/]+)$", input_str)
    if m:
        return m.group(1), m.group(2)

    # owner/repo
    m = re.match(r"^([^/]+)/([^/]+)$", input_str)
    if m:
        return m.group(1), m.group(2)

    print(f"Error: Could not parse '{input_str}' as a GitHub repository.", file=sys.stderr)
    print("Expected formats: owner/repo, https://github.com/owner/repo, git@github.com:owner/repo.git", file=sys.stderr)
    sys.exit(1)


def clone_url(owner: str, repo: str, ssh: bool) -> str:
    if ssh:
        return f"git@github.com:{owner}/{repo}.git"
    return f"https://github.com/{owner}/{repo}.git"


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running: git {' '.join(args)}", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return result


def get_source_dir(args_dir: str | None) -> Path:
    """Resolve source directory from flag > env var > default."""
    if args_dir:
        return Path(args_dir).expanduser().resolve()
    env = os.environ.get("GH_SRC_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / "src"


def get_gh_user() -> str | None:
    """Get GitHub username from env var."""
    return os.environ.get("GH_USER")


def get_gh_token() -> str | None:
    """Get GitHub token from env var (needed for fork API calls)."""
    return os.environ.get("GH_TOKEN")


def fork_repo(owner: str, repo: str, token: str) -> str:
    """Fork a repo on GitHub via API. Returns the fork owner (your username)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/forks"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.post(url, headers=headers, timeout=30)
    if resp.status_code == 202:
        data = resp.json()
        fork_owner = data["owner"]["login"]
        print(f"  Forked {owner}/{repo} → {fork_owner}/{repo}")
        return fork_owner
    elif resp.status_code == 200:
        # Fork already exists
        data = resp.json()
        fork_owner = data["owner"]["login"]
        print(f"  Fork already exists: {fork_owner}/{repo}")
        return fork_owner
    else:
        print(f"Error forking: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)


def get_exclude_dirs() -> set[str]:
    """Get excluded folder names from env var (comma-separated)."""
    raw = os.environ.get("GH_SYNC_EXCLUDE", "")
    if not raw:
        return set()
    return {name.strip() for name in raw.split(",") if name.strip()}


def find_repos(src_dir: Path, exclude: set[str]) -> list[Path]:
    """Find all git repos in src_dir/owner/repo structure."""
    repos = []
    for owner_dir in sorted(src_dir.iterdir()):
        if not owner_dir.is_dir() or owner_dir.name.startswith("."):
            continue
        if owner_dir.name in exclude:
            continue
        for repo_dir in sorted(owner_dir.iterdir()):
            if not repo_dir.is_dir() or repo_dir.name.startswith("."):
                continue
            if repo_dir.name in exclude:
                continue
            if (repo_dir / ".git").exists():
                repos.append(repo_dir)
    return repos


def has_remote(name: str, cwd: Path) -> bool:
    """Check if a git remote exists."""
    result = git("remote", cwd=cwd, check=False)
    return name in result.stdout.splitlines()


def sync_repo(repo_dir: Path) -> None:
    """Pull a repo and sync with upstream if it's a fork."""
    rel = f"{repo_dir.parent.name}/{repo_dir.name}"

    # Check for uncommitted changes
    status = git("status", "--porcelain", cwd=repo_dir, check=False)
    if status.stdout.strip():
        print(f"  ⚠ {rel}: skipped (uncommitted changes)")
        return

    # Pull origin
    result = git("pull", cwd=repo_dir, check=False)
    if result.returncode != 0:
        print(f"  ✗ {rel}: pull failed")
        if result.stderr:
            print(f"    {result.stderr.strip()}")
        return

    # If it has an upstream remote, sync fork
    if has_remote("upstream", repo_dir):
        result = git("fetch", "upstream", cwd=repo_dir, check=False)
        if result.returncode != 0:
            print(f"  ✗ {rel}: upstream fetch failed")
            if result.stderr:
                print(f"    {result.stderr.strip()}")
            return

        # Get default branch
        branch_result = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_dir, check=False)
        branch = branch_result.stdout.strip() or "main"

        result = git("merge", f"upstream/{branch}", "--ff-only", cwd=repo_dir, check=False)
        if result.returncode != 0:
            print(f"  ⚠ {rel}: upstream merge needs manual resolution")
            if result.stderr:
                print(f"    {result.stderr.strip()}")
            return

        # Push the merged changes to origin
        git("push", cwd=repo_dir, check=False)
        print(f"  ✓ {rel} (fork synced with upstream)")
    else:
        print(f"  ✓ {rel}")


def cmd_sync(args: argparse.Namespace) -> None:
    src_dir = get_source_dir(args.dir)
    exclude = get_exclude_dirs()

    # Allow --exclude flag to add more
    if args.exclude:
        for name in args.exclude.split(","):
            name = name.strip()
            if name:
                exclude.add(name)

    if not src_dir.exists():
        print(f"Error: Source directory {src_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    repos = find_repos(src_dir, exclude)

    if not repos:
        print(f"No repositories found in {src_dir}")
        return

    print(f"Syncing {len(repos)} repos in {src_dir}...")
    if exclude:
        print(f"  Excluding: {', '.join(sorted(exclude))}")
    print()

    for repo_dir in repos:
        sync_repo(repo_dir)


def cmd_clone(args: argparse.Namespace) -> None:
    owner, repo = parse_repo(args.repo)
    src_dir = get_source_dir(args.dir)
    gh_user = get_gh_user()
    # Auto-use SSH for own repos
    use_ssh = args.ssh or (gh_user and owner == gh_user)
    do_fork = args.fork

    if do_fork:
        gh_user = get_gh_user()
        gh_token = get_gh_token()
        if not gh_user:
            print("Error: --fork requires GH_USER environment variable.", file=sys.stderr)
            sys.exit(1)
        if not gh_token:
            print("Error: --fork requires GH_TOKEN environment variable.", file=sys.stderr)
            sys.exit(1)

    # Target directory is always based on the original owner/repo
    target = src_dir / owner / repo

    if target.exists():
        print(f"  {target} already exists, pulling...")
        git("pull", cwd=target)
        return

    if do_fork:
        print(f"  Forking {owner}/{repo}...")
        fork_owner = fork_repo(owner, repo, gh_token)

        # Clone the fork via SSH, store in original owner's directory
        url = clone_url(fork_owner, repo, ssh=True)
        print(f"  Cloning fork {fork_owner}/{repo} (SSH) → {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", url, str(target))

        # Add upstream remote pointing to the original repo
        upstream_url = clone_url(owner, repo, ssh=False)
        print(f"  Adding upstream → {upstream_url}")
        git("remote", "add", "upstream", upstream_url, cwd=target)
        git("fetch", "upstream", cwd=target)
    else:
        url = clone_url(owner, repo, use_ssh)
        print(f"  Cloning {owner}/{repo} → {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", url, str(target))

    print(f"  Done: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gh-fetcher",
        description="Clone and manage GitHub repositories in a structured source folder.",
    )
    parser.add_argument(
        "--dir",
        help="Source folder (default: $GH_SRC_DIR or ~/src)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # clone
    clone_parser = subparsers.add_parser("clone", help="Clone a GitHub repository")
    clone_parser.add_argument("repo", help="Repository (owner/repo or full GitHub URL)")
    clone_parser.add_argument("--ssh", action="store_true", help="Clone via SSH instead of HTTPS")
    clone_parser.add_argument("--fork", action="store_true", help="Fork to your account first, clone via SSH, add upstream")

    # sync
    sync_parser = subparsers.add_parser("sync", help="Pull all repos (and sync forks with upstream)")
    sync_parser.add_argument("--exclude", help="Comma-separated folder names to exclude (adds to GH_SYNC_EXCLUDE)")

    args = parser.parse_args()

    if args.command == "clone":
        cmd_clone(args)
    elif args.command == "sync":
        cmd_sync(args)


if __name__ == "__main__":
    main()
