"""A silencer names its rule, a reason and a ticket, so a workaround stays visible (#166)."""

import io
import re
import tokenize

from tests.architecture.support import BACKEND_DIR, relative, source_files

ROOTS = ("apps", "config", "tests")
NOQA_RE = re.compile(r"#\s*noqa\b(?P<rest>.*)", re.IGNORECASE)
CODES_RE = re.compile(r"^:\s*[A-Z]+[0-9]+(\s*,\s*[A-Z]+[0-9]+)*")
TICKET_RE = re.compile(r"#\d+")
TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore", re.IGNORECASE)


def bare_silencers(source):
    """Comments that silence a check without a rule code and a ticket."""
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        comment = token.string
        if TYPE_IGNORE_RE.search(comment):
            # The backend has no typechecker, so nothing needs ignoring.
            found.append((token.start[0], comment))
            continue
        noqa = NOQA_RE.search(comment)
        if noqa is None:
            continue
        rest = noqa.group("rest")
        if not CODES_RE.match(rest) or not TICKET_RE.search(rest):
            found.append((token.start[0], comment))
    return found


def test_the_scan_sees_each_kind_of_bare_silencer():
    source = (
        "a = 1  # noqa\n"
        "b = 2  # noqa: E501\n"
        "c = 3  # type: ignore\n"
        "d = 4  # noqa: E501  generated table #166\n"
        'e = "# noqa"\n'
    )

    assert [line for line, _comment in bare_silencers(source)] == [1, 2, 3]


def test_every_silencer_names_its_rule_and_a_ticket():
    found = [
        f"{relative(path)}:{line} {comment}"
        for root in ROOTS
        for path in source_files(BACKEND_DIR / root)
        for line, comment in bare_silencers(path.read_text())
    ]

    assert found == [], "Write `# noqa: <CODE>  <reason> #<ticket>`, or fix the cause."
