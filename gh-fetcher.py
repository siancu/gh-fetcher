#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "python-dotenv"]
# ///

"""gh-fetcher: Clone and manage GitHub/GitLab repositories in a structured source folder."""

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


def parse_github_repo(input_str: str) -> tuple[str, str]:
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


def parse_gitlab_project(input_str: str, host: str) -> list[str]:
    """Parse a GitLab project path from a path or URL.

    Accepts:
        group/project
        group/subgroup/project
        https://gitlab.example.com/group/subgroup/project
        git@gitlab.example.com:group/subgroup/project.git
    """
    input_str = input_str.rstrip("/")
    if input_str.endswith(".git"):
        input_str = input_str[:-4]

    host_pattern = re.escape(host)

    m = re.match(rf"https?://{host_pattern}/(.+)$", input_str)
    if m:
        input_str = m.group(1)

    m = re.match(rf"ssh://git@{host_pattern}/(.+)$", input_str)
    if m:
        input_str = m.group(1)

    m = re.match(rf"git@{host_pattern}:(.+)$", input_str)
    if m:
        input_str = m.group(1)

    parts = [part for part in input_str.split("/") if part]
    if len(parts) >= 2 and all(part not in {".", ".."} for part in parts):
        return parts

    print(f"Error: Could not parse '{input_str}' as a GitLab project.", file=sys.stderr)
    print(f"Expected formats: group/project, group/subgroup/project, https://{host}/group/project, git@{host}:group/project.git", file=sys.stderr)
    sys.exit(1)


def github_clone_url(owner: str, repo: str, ssh: bool) -> str:
    if ssh:
        return f"git@github.com:{owner}/{repo}.git"
    return f"https://github.com/{owner}/{repo}.git"


def gitlab_clone_url(host: str, project_parts: list[str]) -> str:
    if ":" in host:
        return f"ssh://git@{host}/{'/'.join(project_parts)}.git"
    return f"git@{host}:{'/'.join(project_parts)}.git"


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


def get_gitlab_host() -> str | None:
    """Get GitLab host from env var."""
    host = os.environ.get("GITLAB_HOST")
    if not host:
        return None
    host = host.strip().removeprefix("https://").removeprefix("http://").strip("/")
    return host or None


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
    """Find git repos below src_dir while respecting excluded folder names."""
    repos = []

    def walk(path: Path) -> None:
        for child in sorted(path.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in exclude:
                continue
            if (child / ".git").exists():
                repos.append(child)
                continue
            walk(child)

    walk(src_dir)
    return repos


def get_origin_url(repo_dir: Path) -> str | None:
    """Return the origin URL for a repo, if it has one."""
    result = git("config", "--get", "remote.origin.url", cwd=repo_dir, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def remote_matches_host(remote_url: str | None, host: str) -> bool:
    """Check whether a remote URL points at the requested host."""
    if not remote_url:
        return False
    return (
        remote_url.startswith(f"git@{host}:")
        or remote_url.startswith(f"ssh://git@{host}/")
        or remote_url.startswith(f"https://{host}/")
        or remote_url.startswith(f"http://{host}/")
    )


def has_remote(name: str, cwd: Path) -> bool:
    """Check if a git remote exists."""
    result = git("remote", cwd=cwd, check=False)
    return name in result.stdout.splitlines()


def sync_repo(repo_dir: Path, src_dir: Path) -> None:
    """Pull a repo and sync with upstream if it's a fork."""
    rel = str(repo_dir.relative_to(src_dir))

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


def cmd_sync(args: argparse.Namespace, host: str) -> None:
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

    repos = [repo for repo in find_repos(src_dir, exclude) if remote_matches_host(get_origin_url(repo), host)]

    if not repos:
        print(f"No repositories found in {src_dir}")
        return

    print(f"Syncing {len(repos)} repos from {host} in {src_dir}...")
    if exclude:
        print(f"  Excluding: {', '.join(sorted(exclude))}")
    print()

    for repo_dir in repos:
        sync_repo(repo_dir, src_dir)


def cmd_github_clone(args: argparse.Namespace) -> None:
    owner, repo = parse_github_repo(args.repo)
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
        url = github_clone_url(fork_owner, repo, ssh=True)
        print(f"  Cloning fork {fork_owner}/{repo} (SSH) → {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", url, str(target))

        # Add upstream remote pointing to the original repo
        upstream_url = github_clone_url(owner, repo, ssh=False)
        print(f"  Adding upstream → {upstream_url}")
        git("remote", "add", "upstream", upstream_url, cwd=target)
        git("fetch", "upstream", cwd=target)
    else:
        url = github_clone_url(owner, repo, use_ssh)
        print(f"  Cloning {owner}/{repo} → {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", url, str(target))

    print(f"  Done: {target}")


def cmd_gitlab_clone(args: argparse.Namespace) -> None:
    host = get_gitlab_host()
    if not host:
        print("Error: gitlab clone requires GITLAB_HOST environment variable.", file=sys.stderr)
        sys.exit(1)

    project_parts = parse_gitlab_project(args.project, host)
    src_dir = get_source_dir(args.dir)
    target = src_dir.joinpath(*project_parts)
    project_path = "/".join(project_parts)

    if target.exists():
        print(f"  {target} already exists, pulling...")
        git("pull", cwd=target)
        return

    url = gitlab_clone_url(host, project_parts)
    print(f"  Cloning {project_path} from {host} → {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    git("clone", url, str(target))
    print(f"  Done: {target}")


def cmd_gitlab_sync(args: argparse.Namespace) -> None:
    host = get_gitlab_host()
    if not host:
        print("Error: gitlab sync requires GITLAB_HOST environment variable.", file=sys.stderr)
        sys.exit(1)
    cmd_sync(args, host)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gh-fetcher",
        description="Clone and manage GitHub/GitLab repositories in a structured source folder.",
    )
    parser.add_argument(
        "--dir",
        help="Source folder (default: $GH_SRC_DIR or ~/src)",
    )

    providers = parser.add_subparsers(dest="provider", required=True)

    github_parser = providers.add_parser("github", help="Work with GitHub repositories")
    github_subparsers = github_parser.add_subparsers(dest="command", required=True)

    github_clone_parser = github_subparsers.add_parser("clone", help="Clone a GitHub repository")
    github_clone_parser.add_argument("repo", help="Repository (owner/repo or full GitHub URL)")
    github_clone_parser.add_argument("--ssh", action="store_true", help="Clone via SSH instead of HTTPS")
    github_clone_parser.add_argument("--fork", action="store_true", help="Fork to your account first, clone via SSH, add upstream")

    github_sync_parser = github_subparsers.add_parser("sync", help="Pull all GitHub repos (and sync forks with upstream)")
    github_sync_parser.add_argument("--exclude", help="Comma-separated folder names to exclude (adds to GH_SYNC_EXCLUDE)")

    gitlab_parser = providers.add_parser("gitlab", help="Work with GitLab repositories")
    gitlab_subparsers = gitlab_parser.add_subparsers(dest="command", required=True)

    gitlab_clone_parser = gitlab_subparsers.add_parser("clone", help="Clone a GitLab project over SSH")
    gitlab_clone_parser.add_argument("project", help="Project path (group/project or group/subgroup/project)")

    gitlab_sync_parser = gitlab_subparsers.add_parser("sync", help="Pull all GitLab repos")
    gitlab_sync_parser.add_argument("--exclude", help="Comma-separated folder names to exclude (adds to GH_SYNC_EXCLUDE)")

    args = parser.parse_args()

    if args.provider == "github":
        if args.command == "clone":
            cmd_github_clone(args)
        elif args.command == "sync":
            cmd_sync(args, "github.com")
    elif args.provider == "gitlab":
        if args.command == "clone":
            cmd_gitlab_clone(args)
        elif args.command == "sync":
            cmd_gitlab_sync(args)


if __name__ == "__main__":
    main()
