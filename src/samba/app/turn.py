"""The turn flow shared by planning and work (spec: running-claude, Planning run and Work run).

A use case: it talks to the `AgentRunner` port and to what the orchestrator injects (the store, the
validation call), never to an adapter. The decisions live in `samba.domain.policy`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

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
from samba.domain.questions import Question, add_questions
from samba.domain.sidecar import Sidecar
from samba.domain.states import Stage
from samba.domain.transitions import log_line
from samba.logfmt import kv
from samba.ports import AgentRunner, Clock, IdGenerator

log = logging.getLogger("samba")


class TurnStore(Protocol):
    """What the flow persists. Interim: part 5 of the refactor replaces it with the Tasks port."""

    def save(self, task_id: str, side: Sidecar) -> None: ...
    def append_log(self, task_id: str, line: str) -> None: ...
    def set_section(self, task_id: str, name: str, text: str) -> None: ...
    def render_questions(self, task_id: str, questions: list[Question]) -> None: ...


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
    def __init__(self, agent: AgentRunner, ids: IdGenerator, store: TurnStore,
                 clock: Clock) -> None:
        self.agent = agent
        self.ids = ids
        self.store = store
        self.clock = clock

    async def invoke(self, task_id: str, side: Sidecar, *, stage: Stage, prompt: str,
                     resume: bool, system_prompt: str, location: str,
                     max_cost_usd: float | None) -> AgentReport:
        """One agent turn: assign the session, count the turn, run, add the cost."""
        planning = stage == "plan"
        session = side.plan_session_id if planning else side.session_id
        if not resume or not session:
            session = self.ids.new_session_id()
            resume = False
        if planning:
            side.plan_session_id = session
        else:
            side.session_id = session
        side.turns_total += 1
        self.store.save(task_id, side)
        request = AgentRequest(
            prompt=prompt, session_id=session, resume=resume, system_prompt=system_prompt,
            max_budget_usd=Budget(max_cost_usd, side.cost_usd_total).left, kind=stage,
            location=location, log_name=f"{task_id}/{side.turns_total:03d}")
        log.info(kv("turn_start", task=task_id, n=side.turns_total, resume=resume,
                    session=session, phase="plan" if planning else None))
        res = await self.agent.run(request)
        side.cost_usd_total += res.cost_usd
        side.input_tokens_total += res.input_tokens
        side.output_tokens_total += res.output_tokens
        self.store.save(task_id, side)
        return res

    async def run(self, task_id: str, side: Sidecar, setup: TurnSetup,
                  validate: Callable[[], Awaitable[tuple[bool, str]]],
                  on_turn: Callable[[int], None]) -> Finish | Fail:
        """Run up to `setup.max_turns` turns; return how the run ends."""
        stage = setup.stage
        prompt, resume = setup.prompt, setup.resume
        for turn in range(1, setup.max_turns + 1):
            on_turn(turn)
            budget = Budget(setup.max_cost_usd, side.cost_usd_total)
            gate = budget_gate(budget)
            if gate is not None:
                return gate
            res = await self.invoke(task_id, side, stage=stage, prompt=prompt, resume=resume,
                                    system_prompt=setup.system_prompt, location=setup.location,
                                    max_cost_usd=setup.max_cost_usd)
            if session_reset_needed(res):
                log.info(kv("session_missing", task=task_id))
                if stage == "plan":
                    side.plan_session_id = None
                else:
                    side.session_id = None
                prompt, resume = setup.first_prompt, False
                res = await self.invoke(task_id, side, stage=stage, prompt=prompt, resume=resume,
                                        system_prompt=setup.system_prompt,
                                        location=setup.location, max_cost_usd=setup.max_cost_usd)
            for denial in res.denials:
                self.store.append_log(task_id, log_line(f"permission denied: {denial}",
                                                        self.clock))
            budget = Budget(setup.max_cost_usd, side.cost_usd_total)
            action = decide_after_turn(res, stage, budget, setup.validate_enabled)
            if res.failure is None and not (isinstance(action, Finish)
                                            and action.event == "budget"):
                if stage == "work" and res.outcome == "missing":
                    log.warning(kv("no_structured_output", task=task_id))
                log.info(kv("turn_end", task=task_id, turn=turn, outcome=res.outcome,
                            cost=f"{res.cost_usd:.4f}"))
            match action:
                case Fail():
                    return action
                case Finish(event="planned"):
                    self._plan_sections(task_id, stage, res)
                    return action
                case Finish():
                    return action
                case RecordQuestions(then=done):
                    self._plan_sections(task_id, stage, res)
                    self._ask(task_id, side, stage, res)
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

    def _plan_sections(self, task_id: str, stage: Stage, res: AgentReport) -> None:
        if stage == "plan":
            self.store.set_section(task_id, "Plan", res.plan)
            if res.assumptions:
                self.store.set_section(task_id, "Assumptions", res.assumptions)

    def _ask(self, task_id: str, side: Sidecar, stage: Stage, res: AgentReport) -> None:
        """Record the questions of a blocked run (spec: states, Questions). A blocked run without a valid
        question (for example a permission denial) gets one synthesized from its summary."""
        items = [(q.text, q.context) for q in res.questions]
        if not items:
            context = "Samba synthesized this question: the agent reported blocked without one."
            if res.denials:
                context += " Permission denied: " + ", ".join(res.denials) + "."
            items = [(res.summary or "The agent reported blocked without a question", context)]
        add_questions(side.questions, stage, items, self.clock)
        self.store.render_questions(task_id, side.questions)
