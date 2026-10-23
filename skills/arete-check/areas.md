# The arete areas

Read by the assessing sub-agent. The brief leads with the good: first
the lead (does the item excel at being what it is, and what is it for),
then the twelve areas, each asked two signed questions, then where the
item is excellent and where it devolves, then a recommendation with its
reasons. What is done with it is the caller's. Every finding carries its
evidence, how it was reached and who it touches; no row is given a
grade word. How measured: `count`, `grep`, `gh` (a GitHub query), `git`
(history) or `read` (judgment on reading).

## The lead

The key concept is telos, purpose: does the item fulfil its intended
purpose, and does that purpose serve the next rung's.

1. **Delta** — does the item, by existing, change anything? If not, why
   does it exist. If so, what changes, and for whom.
2. **The chain of aims** — from the item up, one rung each: the item's
   stated aim; its parent's (the issue, card, curia or PR it serves); the
   project's (the repo's README or purpose line); the owner's. For this
   household the owner's rung is the standing orders' "What this is
   for", and it is the top: the chain traces up to it, never judges it.
   Each rung gives the aim in the record's words, where it is stated,
   and whether it serves the rung above. A rung that names no aim is
   work to do: the first such rung is the lead finding, printed before
   anything else; the chain still climbs to the top.
3. **Indication** — is there any indication the item fulfils its
   purpose: `measured` (a number, with its query), `observed` (a
   qualitative or binary sign someone saw: a test that passes, a person
   who used it), `hoped` (an aim stated, no sign yet), or `none`.

## Areas

Each area asks two questions, the good first: **+** in what way does the
item have the capacity to increase human flourishing here, and **−** in
what way does it have the capacity to harm it. Answer both. Where you
looked and found nothing, say `nothing found`; where the area does not
apply, one `n/a` row with its reason. Flag a − finding `harm` when you
would not let the item land with it as it stands.

The order is the anchor's. Flourishing, the good itself, leads; truth
and elegance, which is beauty's name here, follow, with well-formedness
close behind: beauty, goodness and truth were one idea of excellence
before they were three. The rest come after.

1. **flourishing** — + does this increase quality of life, and for
   whom? What good does it make possible that was not possible before?
   − what quality of life does it take away or crowd out?
2. **truth** — + which claims it makes verifiable and which sources it
   names; − where it could state the plausible as the present.
3. **elegance** — + the smallest form that carries the whole meaning;
   − the form that carries more than the meaning, or less.
4. **well-formedness** — + one home per fact, agreement with itself and
   with what it governs; − a fact with two homes, or a contradiction.
5. **privacy** — + what it keeps private, or gives a person control
   over; − what it collects, keeps, moves or exposes about a person, and
   whether any of it lands somewhere public.
6. **security** — + what it closes, checks or refuses; − what it opens,
   trusts or runs, and what an attacker or a prompt injection could do
   through it.
7. **accountability** — + who it makes answerable, and which decision it
   makes traceable to an owner; − who answers when it goes wrong, any
   liability it takes on; for both, who stands behind a rule, how
   firmly, and whether the item changes either.
8. **bias and fairness** — fairness reads two ways, as equal treatment
   and as reward in proportion to what was given; answer for both. + who
   it serves that was served less well before, and what it rewards that
   was earned: merit, or prosocial behaviour; − who it serves less well,
   whether a default in it favours one group, voice or way of working,
   and what it rewards that was not earned.
9. **transparency** — + what it lets the people it touches see of what
   it does and why; − where it hides its working.
10. **social and economic impact** — + the work, time, money, attention
   or relationships it gives back, beyond the person who asked for it;
   − what it takes from them.
11. **judgment kept** — + which decisions it leaves with a person, and
   whether it assists the doing that builds judgment; − which it moves
   from a person to an agent, or replaces; for both, how many decisions
   it adds to a person's day, how often, and of which kind.
12. **cost** — + the tokens, water and screen hours it saves per run;
   − what it spends, and a read-set or a loop with no ceiling is a cost
   with none.

## Format

```
Lead finding: the project rung names no aim — the README says what the
tool does, not for whom or why (README.md:1-20).

Delta: yes — the triage hour becomes a weekly digest the user reads in
five minutes (§1).

| rung    | aim, in the record's words              | where                            | serves the next |
|---------|-----------------------------------------|----------------------------------|-----------------|
| item    | "one digest replaces the triage hour"   | docs/adr/0026.md §1              | yes             |
| parent  | "the user's PR queue stays under ten"   | issue #88                        | yes             |
| project | no aim stated                           | README.md:1-20                   | —               |
| owner   | "a flourishing life, not throughput"    | standing orders, What this is for | the top        |

Indication: hoped — the aim is stated; no count of triage time before
or after (§1).

| area            | ± | finding                                     | evidence             | how   | touches      |
|-----------------|---|---------------------------------------------|----------------------|-------|--------------|
| flourishing     | + | frees the weekly triage hour                | §1, stated aim       | read  | the user     |
| flourishing     | − | nothing found                               |                      | read  |              |
| well-formedness | + | nothing found                               |                      | read  |              |
| well-formedness | − | harm: §3 and §5 disagree on the default     | §3:12, §5:40         | read  | maintainers  |
| privacy         | + | nothing found                               |                      | read  |              |
| privacy         | − | the log keeps the hostnames it prints       | docs/adr/0026.md:41  | read  | the operator |
| security        |   | n/a: reads only, runs nothing               |                      | grep  |              |
| accountability  | + | merge stays with the user                   | §2                   | read  | the user     |
| accountability  | − | no owner for a wrong automatic label        | §3, no owner named   | read  | maintainers  |
| …               |   |                                             |                      |       |              |
| judgment kept   | + | adds no decision; the merge is the user's   | §2                   | count | the user     |
| judgment kept   | − | nothing found                               |                      | read  |              |
| cost            | + | one read a week instead of five             | §1                   | read  | the user     |
| cost            | − | read-set has no ceiling                     | §4, "every repo"     | read  | the user     |

Excellent in: frees the weekly triage hour for the user, and keeps the
merge theirs.
Devolves in: maintainers lose a clear owner for a wrong label, and the
default reads two ways.

Recommendation: not yet, as far as this reader saw — name the project's
aim, and settle §3 against §5; the rest can follow.

Not looked at: the hook the ADR names, and its CI history.
```

Every area gets its rows; `…` stands for the ones this example leaves
out. A `harm` flag opens its finding's text.
