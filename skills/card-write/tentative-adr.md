# A tentative-ADR card

A tentative-ADR card is a ruling card whose decision is already tentatively
taken, living with the codebase until a ruling session writes it up as a
colregs-family ADR (the next number in `docs/adr/`, a budget entry in
`docs/budgets.json`) — never a direct edit to a public repo's docs. It
carries `kind: tentative ADR` and `until:`/`settle:`/`repos:` in place of
`default:`/`undo:`/`risk:`; `until:` holds the date, event and link as on any
ruling card; the decision itself is the card's own
sentence, and `judgment:` gates it as it gates any ruling card:

```markdown
the decision, one sentence ([link](https://...)) kind: tentative ADR until: <date, event and link> settle: <what would settle it> repos: <repo(s) it touches> judgment: <values | risk | direction | legal | people>
```

