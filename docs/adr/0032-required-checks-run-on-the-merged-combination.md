---
status: accepted
---

# Required checks run on the merged combination, with no bypass

Two pull requests can each pass CI against their own base and still break `main` together. On 2026-11-18, #181 banned `useEffect` while #183 added four of them. Both were green, both merged within 100 seconds, and `main` went red at 7bc91ab (fixed by #186, retro #187).

`main` is guarded by two rulesets:

- **main approval**: a pull request, one approval and Code Owner review, plus the deletion and force-push bans. The owner may bypass it only to merge her own human pull requests, which GitHub does not let her approve.
- **main checks**: the required checks `Backend`, `Console`, `Level 2 E2E`, `Celery broker` and `Ticket link`, with **Require branches to be up to date before merging**. It has no bypass actors, so the owner's bypass skips the approval but never the checks or the up-to-date rule.

A required job added to `.github/workflows/ci.yml` is added to **main checks** in the same change.

## Considered Options

- Merge queue: rejected. GitHub offers it only for organization-owned public repositories or for GitHub Enterprise Cloud, and this is a private repository on a personal account.
- One ruleset with strict checks: rejected. The owner's bypass would still skip the checks on her own pull requests, the path #181 took.
- A REVIEW.md rule to check sibling pull requests: rejected. A review reads `main...HEAD` and never sees the other branch; this is mechanical, so it belongs in a guard.

## Consequences

- A pull request that falls behind `main` waits until someone presses **Update branch** (enabled in the repository settings), and CI runs again on the updated branch. Auto-merge does not update the branch by itself, so factory pull requests that overlap need that click.
- Updating a branch pushes a commit. With **Dismiss stale approvals** on, GitHub may drop the approval and ask for it again.
- The rulesets live in GitHub settings, outside the repository. The factory and agents hold no admin token, so they cannot loosen them.
