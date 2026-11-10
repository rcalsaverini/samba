"""The turn flow shared by planning and work (spec: running-claude, Planning run and Work run).

A use case: it talks to the `AgentRunner` and `Tasks` ports and to what the orchestrator injects
(the validation call), never to an adapter. The decisions live in `samba.domain.policy`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from samba.domain.agent import AgentReport, AgentRequest
from samba.domain.policy import (
    Budget,
    Continue,
    Fail,
    Finish,
    RecordQuestions,
    RunValidation,
    after_last_turn,
    budget_gate,
    decide_after_turn,
    session_reset_needed,
)
from samba.domain.states import Stage
from samba.domain.task import Task
from samba.domain.transitions import log_line
from samba.logfmt import kv
from samba.ports import AgentRunner, Clock, IdGenerator, Tasks

log = logging.getLogger("samba")


@dataclass(frozen=True)
class TurnSetup:
    stage: Stage
    system_prompt: str
    location: str
    prompt: str  # the prompt of the first turn
    resume: bool  # whether the first turn resumes the stored session
    first_prompt: str  # sent instead when the stored session is gone
    continue_prompt: str
    validate_failed: Callable[[str], str]  # the validation output tail -> the next prompt
    max_turns: int
    validate_enabled: bool
    max_cost_usd: float | None


class TurnFlow:
    def __init__(self, agent: AgentRunner, ids: IdGenerator, tasks: Tasks,
                 clock: Clock) -> None:
        self.agent = agent
        self.ids = ids
        self.tasks = tasks
        self.clock = clock

    async def invoke(self, task: Task, *, stage: Stage, prompt: str,
                     resume: bool, system_prompt: str, location: str,
                     max_cost_usd: float | None) -> AgentReport:
        """One agent turn: assign the session, count the turn, run, add the cost."""
        planning = stage == "plan"
        session = task.plan_session_id if planning else task.session_id
        if not resume or not session:
            session = self.ids.new_session_id()
            resume = False
        if planning:
            task.plan_session_id = session
        else:
            task.session_id = session
        task.turns_total += 1
        self.tasks.save(task)
        request = AgentRequest(
            prompt=prompt, session_id=session, resume=resume, system_prompt=system_prompt,
            max_budget_usd=Budget(max_cost_usd, task.cost_usd_total).left, kind=stage,
            location=location, log_name=f"{task.id}/{task.turns_total:03d}")
        log.info(kv("turn_start", task=task.id, n=task.turns_total, resume=resume,
                    session=session, phase="plan" if planning else None))
        res = await self.agent.run(request)
        task.cost_usd_total += res.cost_usd
        task.input_tokens_total += res.input_tokens
        task.output_tokens_total += res.output_tokens
        self.tasks.save(task)
        return res

    async def run(self, task: Task, setup: TurnSetup,
                  validate: Callable[[], Awaitable[tuple[bool, str]]],
                  on_turn: Callable[[int], None]) -> Finish | Fail:
        """Run up to `setup.max_turns` turns; return how the run ends."""
        stage = setup.stage
        prompt, resume = setup.prompt, setup.resume
        for turn in range(1, setup.max_turns + 1):
            on_turn(turn)
            budget = Budget(setup.max_cost_usd, task.cost_usd_total)
            gate = budget_gate(budget)
            if gate is not None:
                return gate
            res = await self.invoke(task, stage=stage, prompt=prompt, resume=resume,
                                    system_prompt=setup.system_prompt, location=setup.location,
                                    max_cost_usd=setup.max_cost_usd)
            if session_reset_needed(res):
                log.info(kv("session_missing", task=task.id))
                if stage == "plan":
                    task.plan_session_id = None
                else:
                    task.session_id = None
                prompt, resume = setup.first_prompt, False
                res = await self.invoke(task, stage=stage, prompt=prompt, resume=resume,
                                        system_prompt=setup.system_prompt,
                                        location=setup.location, max_cost_usd=setup.max_cost_usd)
            for denial in res.denials:
                task.add_log(log_line(f"permission denied: {denial}", self.clock))
            if res.denials:
                self.tasks.save(task)
            budget = Budget(setup.max_cost_usd, task.cost_usd_total)
            action = decide_after_turn(res, stage, budget, setup.validate_enabled)
            if res.failure is None and not (isinstance(action, Finish)
                                            and action.event == "budget"):
                if stage == "work" and res.outcome == "missing":
                    log.warning(kv("no_structured_output", task=task.id))
                log.info(kv("turn_end", task=task.id, turn=turn, outcome=res.outcome,
                            cost=f"{res.cost_usd:.4f}"))
            match action:
                case Fail():
                    return action
                case Finish(event="planned"):
                    self._plan_sections(task, stage, res)
                    return action
                case Finish():
                    return action
                case RecordQuestions(then=done):
                    self._plan_sections(task, stage, res)
                    self._ask(task, stage, res)
                    return done
                case RunValidation(summary=summary):
                    ok, tail = await validate()
                    if ok:
                        return Finish("done", "validation passed", summary)
                    prompt = setup.validate_failed(tail)
                case Continue():
                    prompt = setup.continue_prompt
            resume = True
        return after_last_turn(setup.max_turns)

    def _plan_sections(self, task: Task, stage: Stage, res: AgentReport) -> None:
        if stage == "plan":
            task.plan = res.plan
            if res.assumptions:
                task.assumptions = res.assumptions
            self.tasks.save(task)

    def _ask(self, task: Task, stage: Stage, res: AgentReport) -> None:
        """Record the questions of a blocked run (spec: states, Questions). A blocked run without a valid
        question (for example a permission denial) gets one synthesized from its summary."""
        items = [(q.text, q.context) for q in res.questions]
        if not items:
            context = "Samba synthesized this question: the agent reported blocked without one."
            if res.denials:
                context += " Permission denied: " + ", ".join(res.denials) + "."
            items = [(res.summary or "The agent reported blocked without a question", context)]
        task.add_questions(stage, items, self.clock)
        self.tasks.save(task)
