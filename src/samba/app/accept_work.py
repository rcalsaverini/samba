"""`AcceptWork`: `work accept`, the command pattern with a merge as the outside effect (spec: cli)."""

from __future__ import annotations

from samba.app.change_state import Legal, NotAllowed, check_legal
from samba.app.confirm import confirm
from samba.app.machine import Machine
from samba.app.resolve import find_task
from samba.app.results import LOCK_BUSY, Done, Refused, Text, refused
from samba.domain.task_id import TaskId
from samba.domain.validation import accept_tail
from samba.domain.ports import Lock, Tasks, Terminal, Validator, Vcs

EVENT = "work.accept"


class AcceptWork:
    def __init__(self, tasks: Tasks, machine: Machine, terminal: Terminal, lock: Lock,
                 vcs: Vcs, validator: Validator, base_branch: str,
                 validate_command: str | None) -> None:
        self.tasks = tasks
        self.machine = machine
        self.terminal = terminal
        self.lock = lock
        self.vcs = vcs
        self.validator = validator
        self.base = base_branch
        self.validate_command = validate_command

    async def _check(self, task_id: TaskId, branch: str, no_merge: bool) -> Refused | None:
        """State and preflight checks."""
        legal = check_legal(self.tasks, task_id, EVENT, EVENT)
        if isinstance(legal, NotAllowed):
            return refused(legal.message)
        assert isinstance(legal, Legal)
        if not no_merge:
            problem = await self.vcs.preflight(branch)
            if problem:
                return refused(f"{problem}; nothing changed")
        return None

    def _log(self, task_id: TaskId, line: str) -> None:
        task = self.tasks.get(task_id)
        if task is not None:
            task.add_log(line)
            self.tasks.save(task)

    async def run(self, id: str, *, no_merge: bool = False, no_validate: bool = False,
                  yes: bool = False, dry_run: bool = False) -> Done | Text | Refused:
        """`id` is the task id or unique prefix as typed. A dry run is a `Text`."""
        tasks = self.tasks
        task_id = find_task(tasks, id)
        if isinstance(task_id, Refused):
            return task_id
        vcs = self.vcs
        branch = vcs.branch_name(task_id)
        base = self.base
        command = self.validate_command
        failed = await self._check(task_id, branch, no_merge)
        if failed is not None:
            return failed
        do_validate = not no_merge and not no_validate and command is not None
        count = 0 if no_merge else await vcs.commit_count(branch)
        plural = "" if count == 1 else "s"
        if no_merge:
            plan = f"Mark {task_id} done without merging (--no-merge)"
        else:
            plan = f"Merge {branch} into {base} ({count} commit{plural})"
            if do_validate:
                plan += f", then validate with `{command}`"
        if dry_run:
            return Text("\n".join((
                plan,
                f"branch: {branch}\nbase: {base}\ncommits: {count}",
                f"merge: {'no' if no_merge else 'yes (--no-ff)'}",
                f"validate: {command if do_validate else 'skipped'}",
                "final state: done")) + "\n")
        declined = confirm(self.terminal, plan, "work accept", yes)
        if declined is not None:
            return declined

        notes: list[str] = []
        with self.lock.acquire() as held:
            if not held:
                return refused(LOCK_BUSY)
            failed = await self._check(task_id, branch, no_merge)
            if failed is not None:
                return failed
            message = "validation skipped" if no_validate else ""
            if no_merge:
                message = "no merge"
            else:
                found = tasks.get(task_id)
                title = found.title if found else task_id
                attempt = await vcs.begin_merge(branch, f"Merge {branch}: {title}")
                if attempt.status == "conflict":
                    self._log(task_id, f"work.accept: merge failed (conflicts: {attempt.detail})")
                    return refused(f"merge conflict in: {attempt.detail}; merge aborted, task "
                                   "stays in work-review")
                if attempt.status == "error":
                    self._log(task_id, f"work.accept: merge failed ({attempt.detail})")
                    return refused(f"merge failed: {attempt.detail}; merge aborted, task stays "
                                   "in work-review")
                if attempt.status == "already":
                    notes.append(f"samba: {branch} is already merged into {base}; "
                                 "nothing to merge")
                    message = "already merged"
                else:
                    if do_validate:
                        check = await self.validator.run(
                            vcs.checkout_location(), f"{task_id}/accept-validate.log")
                        if not check.ok:
                            await vcs.abort_merge(attempt.restore_point)
                            tail = accept_tail(check)
                            self._log(task_id,
                                      f"work.accept: validation failed after merge: {tail}")
                            return Refused("refused", (
                                "samba: validation failed after merge; merge aborted, task stays "
                                f"in work-review: {tail}",
                                f"samba: full output: {check.log_location}"))
                    commit = await vcs.commit_merge(attempt.restore_point)
                    if not commit.ok:
                        self._log(task_id, f"work.accept: merge failed ({commit.detail})")
                        return refused(f"merge failed: {commit.detail}; merge aborted, task "
                                       "stays in work-review")
                    message = f"merged {commit.detail}" + (
                        ", validated" if do_validate else ", validation skipped" if no_validate
                        else "")
                    if command is None:
                        notes.append("samba: no validate.command; merged without validation")
            if not self.machine.fire(task_id, EVENT, message=message):
                return refused(f"{EVENT} did not apply to {task_id}"
                               + ("" if no_merge else
                                  f" after the merge ({message}); the merge is in {base}"))
        location = tasks.location(task_id) if tasks.get(task_id) is not None else None
        return Done(location, tuple(notes))
