# Recorded `gh` fixtures

These are real `gh` outputs, recorded on 2026-11-09 against
`daedraMex/commerce-platform`, so the tests exercise the JSON shapes the
factory actually receives instead of hand-written fakes. They contain no
secrets. The issues and pull request used are real repo history, not customer
data.

- `gh_issue_list.json` — recorded with:
  `gh issue list --repo daedraMex/commerce-platform --state all --limit 2 --json number,title,body,labels`
  at a time when no open `ready-for-agent` ticket existed. The shape is the same
  as the factory's `--state open --label ready-for-agent` call, and the labels
  are real label objects. It contains test issue #49 and #50.
- `gh_issue_view_open.json` — recorded with:
  `gh issue view 21 --repo daedraMex/commerce-platform --json state`
  (issue #21 is the open test/notes issue).
- `gh_pr_list.json` — recorded with:
  `gh pr list --repo daedraMex/commerce-platform --state all --search 'Phase 4 / 05 in:title' --json body`
  (the merged PR whose body contains `Closes #49`).
- `gh_pr_create.txt` — the URL printed by `gh pr create` when PR #63 was opened;
  captured from the pull request it points at.
