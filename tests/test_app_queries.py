"""In-process tests of the ADR and read-only query use cases over fakes (no adapter)."""

from __future__ import annotations

from samba.app.adr import ListAdrs, SetAdrStatus, ShowAdr, SupersedeAdr
from samba.app.queries import ListQuestions, ListTasks, ShowQuestion, ShowTask, split_target
from samba.app.results import Refused, Table, Text, Written
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.ports import AdrError, AdrInfo

from fake_tasks import FakeTasks
from test_scenarios import FakeClock


class FakeAdrs:
    def __init__(self, *adrs: AdrInfo) -> None:
        self.adrs = {a.number: a for a in adrs}
        self.calls: list[tuple[object, ...]] = []

    def parse_number(self, text: str) -> int:
        if not text.isdigit():
            raise AdrError(f"not an ADR number: {text!r}", 2)
        return int(text)

    def load_all(self) -> list[AdrInfo]:
        return [self.adrs[n] for n in sorted(self.adrs)]

    def find(self, number: int) -> AdrInfo:
        if number not in self.adrs:
            raise AdrError(f"unknown ADR {number:04d}", 2)
        return self.adrs[number]

    def set_status(self, number: int, verb: str, allowed_from: str, status: str) -> list[str]:
        adr = self.find(number)
        if adr.status != allowed_from:
            raise AdrError(f"ADR {number:04d} is {adr.status}; {verb} not allowed", 1)
        self.calls.append(("set_status", number, verb, status))
        return [adr.file]

    def supersede(self, old: int, new: int) -> list[str]:
        self.calls.append(("supersede", old, new))
        return [self.find(old).file, self.find(new).file]


def adr(n: int, status: str) -> AdrInfo:
    return AdrInfo(n, f"docs/adr/{n:04d}-x.md", status, f"Title {n}", f"Sum {n}.", f"text {n}\n")


def adrs() -> FakeAdrs:
    return FakeAdrs(adr(1, "accepted"), adr(2, "proposed"), adr(3, "rejected"))


def refusal(r: object) -> Refused:
    assert isinstance(r, Refused)
    return r


# --- adr ---------------------------------------------------------------------------------------

def test_adr_list_shows_accepted_only_or_all() -> None:
    res = ListAdrs(adrs()).run(False)
    assert res == Table((("NUMBER", "TITLE", "SUMMARY"), ("0001", "Title 1", "Sum 1.")), flex=2)
    full = ListAdrs(adrs()).run(True)
    assert isinstance(full, Table) and full.flex == 3
    assert full.rows[0] == ("NUMBER", "STATUS", "TITLE", "SUMMARY")
    assert [r[1] for r in full.rows[1:]] == ["accepted", "proposed", "rejected"]


def test_adr_show_prints_the_text_and_refuses_unknown_and_bad_numbers() -> None:
    assert ShowAdr(adrs()).run("01") == Text("text 1\n")
    assert refusal(ShowAdr(adrs()).run("9")) == Refused("usage", ("samba: unknown ADR 0009",))
    assert refusal(ShowAdr(adrs()).run("x")).kind == "usage"


def test_adr_accept_and_reject_write_the_file_or_refuse_with_code_1() -> None:
    store = adrs()
    assert SetAdrStatus(store).run("accept", "2") == Written(("docs/adr/0002-x.md",))
    assert store.calls == [("set_status", 2, "accept", "accepted")]
    assert SetAdrStatus(store).run("reject", "2") == Written(("docs/adr/0002-x.md",))
    assert store.calls[-1] == ("set_status", 2, "reject", "rejected")
    wrong = refusal(SetAdrStatus(store).run("accept", "1"))
    assert wrong.kind == "refused" and "not allowed" in wrong.messages[0]
    assert refusal(SetAdrStatus(store).run("accept", "7")).kind == "usage"


def test_adr_supersede_lists_both_files() -> None:
    store = adrs()
    assert SupersedeAdr(store).run("1", "2") == Written(
        ("docs/adr/0001-x.md", "docs/adr/0002-x.md"))
    assert refusal(SupersedeAdr(store).run("1", "zz")).kind == "usage"


# --- queries -----------------------------------------------------------------------------------

def store(*specs: tuple[str, State]) -> FakeTasks:
    tasks = FakeTasks()
    for tid, status in specs:
        tasks.create(Task.new(TaskId(tid), tid.upper(), "", 3, (), status, FakeClock()))
    return tasks


def test_task_list_all_states_in_order_and_filtered_by_prefix() -> None:
    tasks = store(("a", "work-todo"), ("b", "plan-todo"), ("c", "done"))
    full = ListTasks(tasks, FakeClock()).run([])
    assert isinstance(full, Table) and full.flex == 6
    assert full.rows[0] == ("ID", "STATE", "ATTEMPTS", "TURNS", "COST", "LAST", "ERROR")
    assert [r[0] for r in full.rows[1:]] == ["b", "a", "c"]
    assert full.rows[1][1:] == ("plan-todo", "0", "0", "$0.00", "-", "")
    only = ListTasks(tasks, FakeClock()).run(["do"])
    assert isinstance(only, Table) and [r[0] for r in only.rows[1:]] == ["c"]


def test_task_list_unknown_state_is_a_usage_error_listing_the_states() -> None:
    res = refusal(ListTasks(store(), FakeClock()).run(["nope"]))
    assert res.kind == "usage"
    assert res.messages[0].startswith("samba: unknown state 'nope'; valid states:\n  plan-todo")


def test_task_show_renders_lines_and_refuses_unknown() -> None:
    tasks = store(("a", "work-todo"))
    res = ShowTask(tasks, FakeClock()).run("a")
    assert isinstance(res, Text) and res.text.endswith("\n")
    lines = res.text.splitlines()
    assert lines[:3] == ["id: a", "title: A", "state: work-todo"]
    assert "depends_on: -" in lines and "open_questions: 0" in lines
    assert "events:" in lines
    assert refusal(ShowTask(tasks, FakeClock()).run("zz")) == Refused(
        "usage", ("samba: unknown task 'zz'",))


def test_question_list_and_show() -> None:
    tasks = store(("a", "question"))
    tasks.records[TaskId("a")].add_questions("plan", [("why?\nreally", "ctx")], FakeClock())
    listed = ListQuestions(tasks).run()
    assert listed.flex == 4 and listed.rows[0] == ("TASK", "QID", "STAGE", "ASKED", "QUESTION")
    row = listed.rows[1]
    assert row[0] == "a" and row[1].startswith("a/") and row[2] == "plan"
    assert row[4] == "why? really"
    qid = row[1].split("/")[1]
    for target in ("a", f"a/{qid}"):
        shown = ShowQuestion(tasks).run(target)
        assert isinstance(shown, Text)
        assert shown.text.startswith(f"a/{qid}  stage: plan  round: 1  status: open  asked: ")
        assert shown.text.endswith("why?\nreally\n\nContext: ctx\n")


def test_question_show_errors() -> None:
    tasks = store(("a", "work-todo"))
    assert refusal(ShowQuestion(tasks).run("a")) == Refused("usage", ("samba: a has no questions",))
    assert refusal(ShowQuestion(tasks).run("a/q9")).messages == ("samba: unknown question a/q9",)
    assert refusal(ShowQuestion(tasks).run("zz")).messages == ("samba: unknown task 'zz'",)


def test_split_target() -> None:
    assert split_target("a/q1") == ("a", "q1")
    assert split_target("a") == ("a", None)
