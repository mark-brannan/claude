# The arete areas

Read by the assessing sub-agent. Each area gets a grade, its finding,
the evidence, how the grade was reached and who it touches; the brief
ends in a recommendation with its reasons. The user decides. Grades:
`good`, `concern`, `harm`, `n/a`. How measured: `count`, `grep`, `gh`
(a GitHub query), `git` (history) or `read` (judgment on reading).

## Areas

1. **privacy** — what the item collects, keeps, moves or exposes about a
   person, and whether any of it lands somewhere public.
2. **security** — what it opens, trusts or runs; what an attacker or a
   prompt injection could do through it.
3. **accountability** — who answers when it goes wrong; whether a
   decision it makes or enables can be traced to an owner; any liability
   it takes on; who stands behind a rule, and how firmly, and whether the
   item changes either.
4. **bias and fairness** — who it serves less well, and whether a
   default in it favours one group, voice or way of working.
5. **transparency** — whether the people it touches can see what it does
   and why, or whether it hides its working.
6. **social and economic impact** — its effect on work, time, money,
   attention and relationships, beyond the person who asked for it.
7. **flourishing** — the positive sign: does this increase quality of
   life, and for whom? What good does it make possible that was not
   possible before?
8. **judgment kept** — which decisions it moves from a person to an
   agent, and whether it assists the doing that builds judgment or
   replaces it; how many decisions it adds to a person's day, how often,
   and of which kind.
9. **cost** — tokens, water, and screen hours per run; a read-set or a
   loop with no ceiling is a cost with none.
10. **truth** — whether its claims can be verified and its sources are
   named; where it could state the plausible as the present.
11. **elegance** — the smallest form that carries the whole meaning;
   beauty, goodness and truth were one idea of excellence before they
   were three.
12. **well-formedness** — one home per fact, no contradiction with
   itself or with what it governs.

## Format

```
| area            | grade   | finding                                  | evidence                     | how   | touches      |
|-----------------|---------|------------------------------------------|------------------------------|-------|--------------|
| privacy         | concern | the log keeps the hostnames it prints    | docs/adr/0026.md:41          | read  | the operator |
| security        | n/a     | reads only, runs nothing                 |                              | grep  |              |
| accountability  | concern | no owner for a wrong automatic merge     | §3, no owner named           | read  | maintainers  |
| bias/fairness   | n/a     | one user, no defaults over others        |                              | read  |              |
| transparency    | concern | the skip rule is implicit                | skill.md:22                  | read  | the reader   |
| social/economic | good    | no daily review added                    | §4                           | read  | the user     |
| flourishing     | good    | frees the weekly triage hour             | §1, stated aim; no measure   | read  | the user     |
| judgment kept   | good    | merge stays the user's; adds no decision | §2                           | count | the user     |
| cost            | concern | read-set has no ceiling                  | §4, "every repo"             | read  | the user     |
| truth           | good    | each count cites its query               | §2 table                     | gh    | the reader   |
| elegance        | concern | two sections say the skip rule twice     | §3, §5                       | grep  | the reader   |
| well-formedness | harm    | §3 and §5 disagree on the default        | §3:12, §5:40                 | read  | maintainers  |

Recommendation: not yet, as far as this reader saw — §3 and §5 contradict
each other on the default; fix that and name a merge owner, the rest can
follow.

Not looked at: the hook the ADR names, and its CI history.

Decision:
```

The `Decision:` line appears only when a finding is a `harm` or moves a
judgment call off the user (SKILL.md step 4); otherwise the brief ends
at the not-looked-at line.
