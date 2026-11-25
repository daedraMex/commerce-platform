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
- `gh_pr_list.json` — re-recorded on 2026-11-24, unedited, with:
  `gh pr list --repo daedraMex/commerce-platform --state all --search 'Phase 4 / 05 in:title' --json number,body,closingIssuesReferences`
  (merged PR #59, whose body starts `Closes #49. Part of #41.`). GitHub's
  `closingIssuesReferences` lists only #49, with its repository owner and
  name: `Part of` is not a closing keyword, so the factory reads it from the
  link lines itself (#176).
- `gh_pr_list_open.json` — captured on 2026-11-10 with:
  `gh pr list --repo daedraMex/commerce-platform --state merged --limit 3 --json author,headRefName`
  (merged PRs have the same author shape as open ones). GitHub Apps appear as
  `{"is_bot": true, "login": "app/xolo-bot"}`, which is the shape the open-PR
  cap must normalize; it also contains a human PR so the author filter is
  exercised.
- `gh_pr_create.txt` — the URL printed by `gh pr create` when PR #63 was opened;
  captured from the pull request it points at.
- `gh_api_pr_reviews.json` — recorded on 2026-11-12, unedited, with:
  `gh api --paginate repos/daedraMex/commerce-platform/pulls/119/reviews`
  (only re-indented). It holds the owner's real `CHANGES_REQUESTED` review on
  PR #119, with the numeric REST `id` that the comments route needs and the
  `node_id` (`PRR_...`) that must never be sent to a REST route.
