# A User's email is stored lowercase and unique regardless of case

A User logs in with an email that is unique across the platform (ADR-0011). Email providers treat `Ana@x.com` and `ana@x.com` as the same mailbox, but Django only lowercases the domain, so both could become separate Users and the same person would get two logins. We store the whole email lowercase (in the user manager and in `User.save()`), look users up by the lowercased email at login, and back it with a database constraint, `UniqueConstraint(Lower("email"))`, so a write that skips `save()` (such as `QuerySet.update()`) still cannot create a case variant.

## Considered Options

- Keep Django's default (lowercase only the domain): rejected, because it allows duplicate Users for one mailbox.
- Case-insensitive column type (PostgreSQL `citext`): rejected, because it needs a database extension and a non-standard field for a problem a lowercase rule and an expression constraint already solve.
- Constraint only, keeping the email as typed: rejected, because login lookups and comparisons in code would then need to be case-insensitive everywhere.
