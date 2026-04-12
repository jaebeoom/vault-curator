"""CLI 실행 락."""

from __future__ import annotations

from contextlib import contextmanager
import os
import shutil
from pathlib import Path
from typing import Iterator

import typer
from rich.console import Console


SKIP_CLI_LOCK_ENV = "VAULT_CURATOR_SKIP_CLI_LOCK"


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_lock_pid(pid_file: Path) -> None:
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")


def acquire_cli_lock(
    lock_dir: Path,
    console: Console,
    *,
    pid_file: Path | None = None,
    is_pid_alive_fn=is_pid_alive,
) -> bool:
    pid_file = pid_file or (lock_dir / "pid")

    try:
        lock_dir.mkdir()
        write_lock_pid(pid_file)
        return True
    except FileExistsError:
        lock_pid = 0
        if pid_file.exists():
            try:
                lock_pid = int(pid_file.read_text(encoding="utf-8").strip())
            except ValueError:
                lock_pid = 0

        if lock_pid and is_pid_alive_fn(lock_pid):
            console.print(
                f"[yellow]큐레이션이 이미 실행 중입니다 (pid {lock_pid}).[/yellow]"
            )
            return False

        console.print("[yellow]stale curation lock 제거 후 재시도합니다.[/yellow]")
        shutil.rmtree(lock_dir, ignore_errors=True)
        lock_dir.mkdir()
        write_lock_pid(pid_file)
        return True


def release_cli_lock(lock_dir: Path) -> None:
    shutil.rmtree(lock_dir, ignore_errors=True)


@contextmanager
def cli_lock(
    lock_dir: Path,
    console: Console,
    *,
    skip_env_var: str = SKIP_CLI_LOCK_ENV,
    pid_file: Path | None = None,
) -> Iterator[None]:
    if os.getenv(skip_env_var) == "1":
        yield
        return

    if not acquire_cli_lock(lock_dir, console, pid_file=pid_file):
        raise typer.Exit(0)

    try:
        yield
    finally:
        release_cli_lock(lock_dir)
