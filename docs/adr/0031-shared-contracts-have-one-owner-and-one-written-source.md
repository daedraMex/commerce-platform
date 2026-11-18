---
status: accepted
---

# Shared contracts have one owner and one written source

A **contract** is an agreement that more than one ticket or module depends on, so two pull requests can each pass CI while disagreeing about it. Three kinds count as contracts:

- a Celery task's name and kwargs;
- a port signature that one module implements and another calls;
- an entity state machine (its states, the action that moves to each state, the counters each path changes and the error `code` each refusal returns) that more than one ticket produces or consumes.

Each contract has exactly one owner: the ticket that introduces it, or an ADR when the contract is a decision in its own right. Its written source is `docs/contracts/<module>.md`, which records the contract as merged code implements it and names the owner. The ticket that defines a contract writes or updates that file in the same pull request. A ticket that changes a contract it does not own also updates the file, and every consumer it can find, in that same pull request.

Tickets declare the contracts they touch in a **Contracts** section, next to **Blocked by**, with three verbs: **defines** (the ticket is the owner), **changes** (the ticket alters a contract it does not own) and **consumes** (the ticket relies on it unchanged). For example: "Changes `photos.submission-states`; consumes `photos.process-photo-task`." Contract ids are `<module>.<name>` and are the headings of the contract file. Two tickets that define or change the same contract must not be in flight at once.

## Considered Options

- Leave contracts implicit in the code: rejected. #131 and #132 were built in parallel and disagreed on the task name, the state the worker receives and the queue port. Both passed CI, and the conflict surfaced only in review.
- Describe contracts inside each ticket: rejected. The same contract would be copied into several tickets and drift between them.
- Generate the contract from the code (OpenAPI-style): rejected for now. There is no tool for task kwargs or state machines, and a hand-written file read in review is enough at this size.

## Consequences

- `docs/contracts/photos.md` records the photos contracts as merged in #131 and the B12 pipeline.
- `/to-tickets` adds the **Contracts** section to every ticket it writes.
- REVIEW.md rule 2 (contracts match across open pull requests) has a file to check against.
- The night factory can refuse to start a ticket whose contract an open pull request is changing (#144); until then, the owner keeps two such tickets apart by hand.
