# The arete areas

Read by the assessing sub-agent. Each area gets a question, its evidence
and who it touches. No marks: the brief carries what the user needs to
grade, and the grade is theirs.

## Areas

1. **privacy** — what the item collects, keeps, moves or exposes about a
   person, and whether any of it lands somewhere public.
2. **security** — what it opens, trusts or runs; what an attacker or a
   prompt injection could do through it.
3. **accountability** — who answers when it goes wrong; whether a
   decision it makes or enables can be traced to an owner; any liability
   it takes on.
4. **bias and fairness** — who it serves less well, and whether a
   default in it favours one group, voice or way of working.
5. **transparency** — whether the people it touches can see what it does
   and why, or whether it hides its working.
6. **social and economic impact** — its effect on work, time, money,
   attention and relationships, beyond the person who asked for it.
7. **flourishing** — the positive sign: does this increase quality of
   life, and for whom? What good does it make possible that was not
   possible before?

## Format

```
| area            | question                                   | evidence                     | touches        |
|-----------------|--------------------------------------------|------------------------------|----------------|
| privacy         | Does the log keep hostnames it prints?     | docs/adr/0026.md:41          | the operator   |
| security        | n/a — reads only, runs nothing             |                              |                |
| accountability  | Who owns a wrong automatic merge?          | §3, no owner named           | maintainers    |
| bias/fairness   | n/a — one user, no defaults over others    |                              |                |
| transparency    | Is the skip rule visible to the reader?    | skill.md:22, rule is implicit| the reader     |
| social/economic | Does it add a daily review to someone?     | §4, "every morning"          | the user       |
| flourishing     | Does it free an hour a week, or add one?   | §1, stated aim; no measure   | the user       |

Grade:
```
