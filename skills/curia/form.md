## Form

A curia starts open-ended. [template.md](template.md) seeds one open
question, *what form does this curia need to take?*, with the forms the
skill can offer, and nothing else. **The user directs the early sittings.**
The agent never forces a form: it proposes one only when the dialogue has
taken a shape it is confident matches one, says which and why in one
line, and waits for the word. A form, once the user chooses it, adds its
own file beside `digest.md`, a sidecar, from its file under
[forms/](forms/); the digest stays the one ADR-shaped document:

| Form | Ancestor | Fits when |
|---|---|---|
| working-backwards | Amazon PR/FAQ; Covey's "begin with the end in mind" | the end state is felt but unwritten |
| problem-then-solution | the design doc's diagnosis-then-design | the pain is clear, the fix is not |
| bdd | behaviour-driven development, given/when/then | behaviour is the contract |
| mvp-and-narrative | lean startup's MVP, plus its story | the user wants to test by using |
| success-metric | OKR / North Star metric | the measure is the hard part |

A curia may combine two or more forms, one sidecar each, and may change
them; the user says which. problem-then-solution is the digest's own
**The problem** and **The design**, so it adds no file. Each
choice is a dated line in `decided.md` with its reference, and a change is a new
line naming the one it replaces. A dropped form's sidecar leaves the
folder with it; what it held that still earns its place moves to
`decided.md` or **Open questions**, and lint shows the move: a reversal is
a finding, not an error.

A section's `<!-- -->` comment is a rule or a prompt. A rule says how the
section is kept (*Derived; rewritten in place…*) and stays. A prompt says
what to write (*One number, how it is measured…*) and is replaced by its
answer the first time the section is written.

