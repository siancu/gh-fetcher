#!/usr/bin/env -S uv run
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


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
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


def cmd_clone(args: argparse.Namespace) -> None:
    owner, repo = parse_repo(args.repo)
    src_dir = get_source_dir(args.dir)
    use_ssh = args.ssh
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

    args = parser.parse_args()

    if args.command == "clone":
        cmd_clone(args)


if __name__ == "__main__":
    main()
