# References and reading list

The sources behind the working loop in this repo: the skills and hooks under
`.claude/`, the board, the guards, and the standing orders. Each entry gives
the idea in one line and what it maps to here in one line. Every citation was
checked against the web on 2026-09-29. An entry the web could not confirm is
marked unverified, never dropped.

## Framing

Solace's, verbatim.

- Two loops. Loop one is the work (grind). Loop two is questioning the governing
  ideas behind the work (confer). Both are agent-assisted; loop two is never
  agent-authored. Solace generates the concepts and the orders; the agent is
  secretary and editor, not creator. Prose-budget, the colregs ADR proposal
  mechanism and churn-guard are earlier attempts at agent-assisted loop two.
- The agora is fast decisions, wholly Solace's; the agent brings them, Solace rules.
  The confer is slow decisions, still Solace's, with the agent bringing information
  and practising reflection, expansion and refinement.
- The autonomy slider (Karpathy) has a useful kernel, not fully embraced: model and
  effort are chosen per task, and the terms that move the slider up are being
  qualified: risk, values, judgment, reversibility.

## Loop one: the work

- **Shewhart, W. A. (1939).** *Statistical Method from the Viewpoint of Quality
  Control.* Graduate School, US Department of Agriculture; Dover reprint 1986.
  [archive.org](https://archive.org/details/CAT10502416)
  - Idea: specification, production and inspection "must go in a circle instead
    of in a straight line". The origin of every improvement cycle below.
  - Maps to: the unit of grind. An item is specified (a card or issue), produced
    (a PR) and inspected (review) before the next one is pulled.
- **Deming, W. E. (1986).** *Out of the Crisis.* MIT Center for Advanced
  Engineering Study. **Deming, W. E. (1993).** *The New Economics.* MIT CAES.
  History of the acronym: Moen, R. D. and Norman, C. L. (2010), "Circling
  Back", *Quality Progress*, November 2010.
  [deming.org](https://deming.org/wp-content/uploads/2020/06/PDSA_History_Ron_Moen.pdf)
  - Idea: Plan, Do, Study, Act. Deming insisted on Study, never Check; PDCA is
    the Japanese recasting of his 1950 lectures, which he disowned.
  - Maps to: Study is the step loop one skips by default. The metrics hooks and
    the narrative log are where study happens; loop two reads them.
- **Rother, M. (2009).** *Toyota Kata: Managing People for Improvement,
  Adaptiveness and Superior Results.* McGraw-Hill.
  [archive.org](https://archive.org/details/toyotakatamanagi0000roth)
  - Idea: an improvement kata (vision, current condition, target condition,
    iterate past obstacles) and a coaching kata of the same five questions
    every time.
  - Maps to: the hand-off prompt and the resume block. Same shape every
    session, a target condition, the obstacle named, model and effort set.
- **Ries, E. (2011).** *The Lean Startup.* Crown Business.
  [wikipedia](https://en.wikipedia.org/wiki/The_Lean_Startup)
  - Idea: build, measure, learn. Ship the smallest thing that tests the
    assumption, then persevere or pivot.
  - Maps to: one PR per item and the review band of five to ten. The batch
    stays small enough to learn from before the next is cut.
- **Sy, D. (2007).** "Adapting Usability Investigations for Agile
  User-centered Design." *Journal of Usability Studies* 2(3). Popularised as
  "dual-track" by Cagan, M. (2012), "Dual-Track Agile", svpg.com, and Patton,
  J. (2017), "Dual Track Development is not Duel Track".
  [svpg.com](https://www.svpg.com/dual-track-agile/)
  - Idea: discovery and delivery run as two parallel tracks of one team,
    connected daily, never a hand-off. The pattern is Sy's (and Lynn Miller's,
    2005); Cagan later dropped the term for "continuous discovery".
  - Maps to: confer and grind are the two tracks. The board is the daily
    connection where discovery feeds delivery.
- **Boyd, J. R. (1976).** "Destruction and Creation" (essay). **Boyd, J. R.
  (1995).** *The Essence of Winning and Losing* (briefing; the only place Boyd
  drew the loop).
  [coljohnboyd.com](https://www.coljohnboyd.com/static/documents/1976-09-03__Boyd_John_R__Destruction_and_Creation.pdf)
  - Idea: observe, orient, decide, act, with orientation shaping every stage.
  - Maps to: worklist observes, the continuity brief and checkpoint orient, a
    ruling decides, grind acts.
- **Ohno, T. (1988).** *Toyota Production System: Beyond Large-Scale
  Production.* Productivity Press (Japanese original 1978). **Anderson, D. J.
  (2010).** *Kanban: Successful Evolutionary Change for Your Technology
  Business.* Blue Hole Press.
  [routledge](https://www.routledge.com/Toyota-Production-System-Beyond-Large-Scale-Production/Ohno/p/book/9780915299140)
  - Idea: kanban is the pull signal that stops overproduction (Ohno).
    Visualise work, limit work in progress, manage flow (Anderson).
  - Maps to: the WIP limit of two to three sessions, the review band, and
    grind pausing dispatch when the band is full.
- **Imai, M. (1986).** *Kaizen: The Key to Japan's Competitive Success.*
  McGraw-Hill.
  [archive.org](https://archive.org/details/kaizen00masa)
  - Idea: continuous small improvements by everyone, every day, outperform
    episodic innovation.
  - Maps to: churn-guard. One script per PR, a fixed line budget, and the
    ceiling raised only by the human.
- **Allen, D. (2001).** *Getting Things Done: The Art of Stress-Free
  Productivity.* Viking.
  [archive.org](https://archive.org/details/gettingthingsdon00alle)
  - Idea: capture every commitment in a trusted external system, clarify the
    next action, review on a schedule.
  - Maps to: the global board, a card written at discovery, and the sweep.
    Capture is not activation.

## Loop two: the governing ideas

- **Argyris, C. and Schön, D. A. (1974).** *Theory in Practice: Increasing
  Professional Effectiveness.* Jossey-Bass.
  [eric.ed.gov](https://eric.ed.gov/?id=ED344506)
  - Idea: espoused theory versus theory-in-use. Single-loop learning corrects
    the action inside the governing variables; double-loop changes the
    variables. Model I (win, control, defend) blocks double-loop learning;
    Model II (valid information, free informed choice) allows it. Model I and
    II are introduced in this book, not the 1978 one.
  - Maps to: the standing orders are espoused theory. The counters (decisions
    pushed, corrections, rebukes) measure the theory-in-use against them. A
    confer is the double loop.
- **Argyris, C. (1977).** "Double Loop Learning in Organizations." *Harvard
  Business Review* 55(5).
  [hbr.org](https://hbr.org/1977/09/double-loop-learning-in-organizations)
  - Idea: organisations hide errors behind single-loop routines; double-loop
    learning questions the policies and objectives themselves.
  - Maps to: grind never rewrites a rule. Only a confer may, and only the
    human authors the change.
- **Argyris, C. and Schön, D. A. (1978).** *Organizational Learning: A Theory
  of Action Perspective.* Addison-Wesley.
  [archive.org](https://archive.org/details/organizationalle00chri)
  - Idea: the theory of action applied to organisations, adding
    deutero-learning: learning how to learn.
  - Maps to: the narrative log's "for next time" list and the decision-load
    counters read over days rather than per chat.
- **Flood, R. L. and Romm, N. R. A. (1996).** *Diversity Management: Triple
  Loop Learning.* Wiley.
  [wiley](https://onlinelibrary.wiley.com/doi/abs/10.1002/(SICI)1099-1743(199711/12)14:6%3C425::AID-SRES191%3E3.0.CO;2-X)
  - Idea: three loops. Are we doing things right, are we doing the right
    things, and is rightness buttressed by mightiness (who holds the power to
    decide).
  - Maps to: the third loop is the framing's rule that loop two is never
    agent-authored. Competence does not confer authority.
- **Engelbart, D. C. (1962).** *Augmenting Human Intellect: A Conceptual
  Framework.* SRI Summary Report AFOSR-3223. **Engelbart, D. C. (1992).**
  "Toward High-Performance Organizations: A Strategic Role for Groupware."
  *GroupWare '92.* The A-B-C model first appears in Engelbart and Engelbart
  (1991), "Bootstrapping Organizations into the 21st Century".
  [dougengelbart.org](https://www.dougengelbart.org/pubs/augment-3906.html)
  - Idea: A is the core work, B improves A, C improves B; bootstrapping is
    investing in C. The 1962 report gives the augmentation framework; A-B-C is
    the 1991 and 1992 papers, not 1962.
  - Maps to: grind is A, the skills, hooks and guards are B, this list and the
    confer are C.
- **Beer, S. (1972).** *Brain of the Firm.* Allen Lane; 2nd ed. Wiley 1981.
  **Beer, S. (1979).** *The Heart of Enterprise.* Wiley. **Beer, S. (1985).**
  *Diagnosing the System for Organizations.* Wiley.
  [wiley](https://www.wiley.com/en-us/Brain+of+the+Firm,+2nd+Edition-p-9780471948391)
  - Idea: the Viable System Model. Five recursive systems, and an algedonic
    (pain and pleasure) signal that bypasses the normal filters to reach the
    top at once. The algedonic channel is in the 1972 edition.
  - Maps to: the Stop hook's nag thresholds and the decision-load counter are
    algedonic channels. They interrupt work in progress rather than wait for the
    log to be read. The confer is System 4 and 5.
- **Ashby, W. R. (1956).** *An Introduction to Cybernetics.* Chapman and Hall.
  Law of requisite variety, chapter 11.
  [wikipedia](https://en.wikipedia.org/wiki/An_Introduction_to_Cybernetics)
  - Idea: only variety can absorb variety. A regulator needs at least as many
    states as the disturbances it controls.
  - Maps to: model and effort chosen per task, and a hand-off that names both.
    Variety matched to the item, not a single setting for everything.
- **Nygard, M. (2011).** "Documenting Architecture Decisions." Cognitect blog,
  15 November 2011.
  [cognitect.com](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
  - Idea: each significant decision is a short numbered record of context,
    decision, status and consequences, immutable once accepted.
  - Maps to: `docs/decisions.md` and the colregs tentative-ADR card. The agent
    drafts, the human accepts, and the record names its owner and date.
- **Martraire, C. (2019).** *Living Documentation: Continuous Knowledge Sharing
  by Design.* Addison-Wesley.
  [informit](https://www.informit.com/store/living-documentation-continuous-knowledge-sharing-by-9780134689326)
  - Idea: documentation that is generated from, and evolves with, the code at
    little extra cost. Anything else rots.
  - Maps to: prose-budget, and the runbook rule against point-in-time status.
    A document nothing checks is exhaust.

## Fast and slow decisions: the agora and the confer

- **Kahneman, D. (2011).** *Thinking, Fast and Slow.* Farrar, Straus and
  Giroux. The terms are from Stanovich, K. E. and West, R. F. (2000),
  *Behavioral and Brain Sciences* 23(5).
  [macmillan](https://us.macmillan.com/books/9780374533557/thinkingfastandslow/)
  - Idea: fast, automatic System 1 forms impressions; slow, effortful System 2
    monitors and occasionally overrides, but is lazy.
  - Maps to: the agora is built for System 1, a question whose answer is one
    word. A confer is System 2, opened only for a true judgment question.
- **Klein, G. A. (1998).** *Sources of Power: How People Make Decisions.* MIT
  Press. Original study: Klein, Calderwood and Clinton-Cirocco (1986), *Human
  Factors Society 30th Annual Meeting.*
  [mit.edu](https://direct.mit.edu/books/book/3647/Sources-of-PowerHow-People-Make-Decisions)
  - Idea: recognition-primed decision. Experts recognise a situation as
    typical, simulate one option, and act; they rarely compare.
  - Maps to: a ruling card carries default, undo, until and risk, so the ruling
    is recognition rather than comparison. Bring a recommendation, not a menu.
- **Klein, G. (2007).** "Performing a Project Premortem." *Harvard Business
  Review* 85(9).
  [hbr.org](https://hbr.org/2007/09/performing-a-project-premortem)
  - Idea: assume the project has already failed and list the reasons. Dissent
    becomes legitimate before commitment.
  - Maps to: the risk field on a card, and the rule to argue before the order,
    once, plainly.
- **Simon, H. A. (1971).** "Designing Organizations for an Information-Rich
  World." In Greenberger (ed.), *Computers, Communications, and the Public
  Interest.* Johns Hopkins Press.
  [pdf](https://veryinteractive.net/pdfs/simon_designing-organizations-for-an-information-rich-world.pdf)
  - Idea: a wealth of information creates a poverty of attention. Design the
    organisation around allocating attention.
  - Maps to: the decision-load budget across a day. The dearest decision is
    one that should have been obvious to the agent.
- **Snowden, D. J. and Boone, M. E. (2007).** "A Leader's Framework for
  Decision Making." *Harvard Business Review* 85(11). **Kurtz, C. F. and
  Snowden, D. J. (2003).** "The new dynamics of strategy." *IBM Systems
  Journal* 42(3).
  [hbr.org](https://hbr.org/2007/11/a-leaders-framework-for-decision-making)
  - Idea: Cynefin. Clear, complicated, complex, chaotic and disorder each need
    a different way of sensing and deciding.
  - Maps to: sorting an item into grind (complicated toil), agora (clear) or
    confer (complex). The confer rate measures how well the sort is going.
- **Bezos, J. P. (2016).** *2015 Letter to Shareholders.* Amazon.com, Inc.
  [amazon](https://s2.q4cdn.com/299287126/files/doc_financials/annual/2015-Letter-to-Shareholders.PDF)
  - Idea: Type 1 decisions are one-way doors and deserve deliberation. Type 2
    are two-way doors and should be made quickly by individuals.
  - Maps to: the one-way-door test. Name the default and its undo, and take
    the default when the undo is a revert nobody has built on.
- **Rogers, P. and Blenko, M. W. (2006).** "Who Has the D? How Clear Decision
  Roles Enhance Organizational Performance." *Harvard Business Review*,
  January 2006.
  [hbr.org](https://hbr.org/2006/01/who-has-the-d-how-clear-decision-roles-enhance-organizational-performance)
  - Idea: RAPID. Name who recommends, agrees, performs, gives input and
    decides.
  - Maps to: the agent recommends and performs; the human decides. Decisions
    sort by kind (toil or judgment), never by size.

## The order: writing intent so it can be carried out

- **US Army (2019).** *ADP 6-0, Mission Command: Command and Control of Army
  Forces.* Headquarters, Department of the Army, July 2019. **Bungay, S.
  (2010).** *The Art of Action.* Nicholas Brealey. Origin in Moltke's 1869
  regulations for senior commanders: unverified except as cited through Bungay.
  [fas.org](https://irp.fas.org/doddir/army/adp6_0.pdf)
  - Idea: Auftragstaktik and commander's intent. State the purpose and the end
    state; leave the how to whoever is closest to the situation.
  - Maps to: "make it so", and the hand-off prompt. Intent, risk and what
    matters come from the human; names, order and tooling are the agent's.
- **Vogels, W. (2006).** "Working Backwards." *All Things Distributed*, 1
  November 2006. **Bryar, C. and Carr, B. (2021).** *Working Backwards.* St.
  Martin's Press.
  [allthingsdistributed.com](https://www.allthingsdistributed.com/2006/11/working_backwards.html)
  - Idea: write the press release and the FAQ first, then build the least that
    makes them true.
  - Maps to: the definition of ready for an agora item. It is offered only when
    its context lets the human answer without asking.
- **Fowler, M. (2004).** "Specification By Example." bliki, 18 March 2004.
  **Adzic, G. (2011).** *Specification by Example.* Manning.
  [martinfowler.com](https://martinfowler.com/bliki/SpecificationByExample.html)
  - Idea: concrete examples are both the requirement and the acceptance test.
  - Maps to: show, don't tell. A value as the thing it produces, a display as
    its mockup, and a test file beside every hook.
- **North, D. (2006).** "Introducing BDD." *Better Software*, March 2006.
  [dannorth.net](https://dannorth.net/introducing-bdd/)
  - Idea: describe behaviour in stakeholder language, given, when, then, and
    let it drive development.
  - Maps to: a ruling card's until and undo fields are its given, when, then.
- **Lütke, T. (2025).** Post on X, 18 June 2025. **Karpathy, A. (2025).** Post
  on X, 25 June 2025, endorsing Lütke's term.
  [x.com](https://x.com/karpathy/status/1937902205765607626)
  - Idea: context engineering. Provide all the context that makes the task
    plausibly solvable; fill the window with the right information for the
    next step. Dates computed from the post identifiers; X refused fetches.
  - Maps to: the continuity brief, the resume block, and subagents that spend
    their own context and return a summary.
- **Anthropic (2025).** "Effective context engineering for AI agents."
  Engineering blog, 29 September 2025. **Schluntz, E. and Zhang, B. (2024).**
  "Building effective agents." 19 December 2024.
  [anthropic.com](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  - Idea: the context window is a finite resource: compaction, structured
    notes, subagents. Prefer simple composable workflows over frameworks.
  - Maps to: the checkpoint file as structured notes, and grind as a workflow
    that never chooses its own goals.

## The autonomy slider: what stays with the human

- **Sheridan, T. B. and Verplank, W. L. (1978).** *Human and Computer Control
  of Undersea Teleoperators.* MIT Man-Machine Systems Laboratory.
  [archive.org](https://archive.org/details/DTIC_ADA057655)
  - Idea: ten levels of supervisory control, from fully manual to the computer
    acting without telling the human.
  - Maps to: the slider itself. Where an item sits on the scale is decided by
    the one-way-door test, not by the agent's confidence.
- **Parasuraman, R., Sheridan, T. B. and Wickens, C. D. (2000).** "A Model for
  Types and Levels of Human Interaction with Automation." *IEEE Transactions
  on Systems, Man, and Cybernetics, Part A* 30(3).
  [doi](https://doi.org/10.1109/3468.844354)
  - Idea: the level is chosen separately for four functions: acquire
    information, analyse it, select a decision, implement the action.
  - Maps to: the framing's qualification. Acquire and analyse may run high (the
    agent brings information); select stays with the human wherever risk,
    values, judgment or reversibility are in play.
- **Bainbridge, L. (1983).** "Ironies of Automation." *Automatica* 19(6).
  [sciencedirect](https://www.sciencedirect.com/science/article/abs/pii/0005109883900468)
  - Idea: automating the easy parts leaves the human deskilled yet responsible
    for the hardest cases.
  - Maps to: where the doing builds the judgment, assist rather than replace.
    Loop two is never agent-authored so the judgment stays exercised.
- **Horvitz, E. (1999).** "Principles of Mixed-Initiative User Interfaces."
  *CHI '99.*
  [acm.org](https://dl.acm.org/doi/10.1145/302979.303030)
  - Idea: weigh the expected utility of acting, asking, or deferring under
    uncertainty, and hold a dialogue when it pays.
  - Maps to: the three exits of a judgment call (omit, card, ask), and the
    higher cost of a gate question than a scoping one.
- **Karpathy, A. (2025).** "Software Is Changing (Again)." Keynote, Y
  Combinator AI Startup School, 17 June 2025.
  [ycombinator.com](https://www.ycombinator.com/library/MW-andrej-karpathy-software-is-changing-again)
  - Idea: products should expose an autonomy slider so the user chooses how
    much the AI does.
  - Maps to: the framing's kernel. Model and effort per task, and the terms
    that move the slider up are being qualified.

## Prior art: recent tooling

Dates are as found on 2026-09-29.

- **GitHub Spec Kit.** Delimarsky, D., GitHub blog, 2 September 2025, from
  John Lam's research. `/specify`, `/plan`, `/tasks`, then implement.
  [github.blog](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
  - Maps to: the card, issue, PR ladder. The difference is who writes the
    spec: there the agent drafts it; here the order is the human's.
- **AWS Kiro.** Preview 14 July 2025, general availability 17 November 2025.
  Specs (requirements, design, tasks) and hooks on file events.
  [kiro.dev](https://kiro.dev/blog/general-availability/)
  - Maps to: the hooks under `.claude/hooks`, the same idea on session events
    rather than file events.
- **Beads.** Yegge, S., 13 October 2025. A git-backed, dependency-aware issue
  tracker that gives coding agents memory across sessions.
  [github.com](https://github.com/gastownhall/beads)
  - Maps to: the board and the checkpoints in the private state repo. Both put
    agent memory in git; here it is kept out of the public tree.
- **Gas Town.** Yegge, S., 1 January 2026. An orchestrator running many
  parallel coding agents in named roles on top of Beads.
  [github.com](https://github.com/gastownhall/gastown)
  - Maps to: orchestrate and grind, at smaller scale: one worker per issue, a
    review band, and the human as the only mayor.
- **The Ralph Wiggum loop.** Huntley, G., 14 July 2025. Rerun the agent on the
  same prompt until the work is done; later an official Claude Code plugin
  (plugin date unverified).
  [ghuntley.com](https://ghuntley.com/ralph/)
  - Maps to: grind is a Ralph loop with a budget, a per-repo lock, and a pause
    at the review band.
- **AGENTS.md.** August 2025; donated to the Linux Foundation December 2025.
  One root file of agent-facing project instructions.
  [agents.md](https://agents.md/)
  - Maps to: `CLAUDE.md` and the standing orders.
- **OpenSpec.** Fission-AI, active since 2025; first release date unverified.
  Delta specs that describe a change relative to the current specs.
  [github.com](https://github.com/Fission-AI/OpenSpec/)
  - Maps to: the tentative-ADR card, a proposed change relative to the settled
    record.
- **BMAD Method.** BMad Code, repository since April 2025. Named agent roles
  carry an idea through brief, PRD, architecture and stories. v6 installs into
  `_bmad/` and keeps plans in `_bmad-output/planning-artifacts/`.
  [github.com](https://github.com/bmad-code-org/BMAD-METHOD)
  - Maps to: the skills as named roles. There the planning documents are the
    agents' output; here the governing documents are the human's.
- **Cursor rules.** Project rules are `.mdc` files in `.cursor/rules/`, with
  frontmatter `description`, `globs` and `alwaysApply`; a plain `.md` there is
  ignored. Cursor also reads `AGENTS.md`, nested.
  [cursor.com](https://cursor.com/docs/context/rules)
  - Maps to: `.claude/rules/`, loaded by the files being worked on.
- **Aider conventions.** A small markdown file, by convention `CONVENTIONS.md`,
  loaded read-only with `--read` or a `read:` line in `.aider.conf.yml`.
  [aider.chat](https://aider.chat/docs/usage/conventions.html)
  - Maps to: `.claude/rules/code.md` and `writing.md`.
- **GitHub Copilot custom instructions.** `.github/copilot-instructions.md`
  for the repository, `.github/instructions/*.instructions.md` by path glob,
  and for agents `AGENTS.md` anywhere in the tree, nearest wins, or one
  `CLAUDE.md` or `GEMINI.md` at the root.
  [docs.github.com](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
  - Maps to: the same split as `CLAUDE.md` and `.claude/rules/`.
- **adr-tools.** Pryce, N., 2016. Shell scripts that number and link
  Nygard-style records in `doc/adr/`; `adr init <dir>` records another
  location in `.adr-dir`.
  [github.com](https://github.com/npryce/adr-tools)
  - Maps to: `docs/decisions.md`, one file rather than one per record.
- **MADR.** Markdown Architectural Decision Records; 4.0.0 on 17 September
  2024. Records named `NNNN-title-with-dashes.md` in `docs/decisions/`, with
  the options considered and their pros and cons.
  [adr.github.io](https://adr.github.io/madr/)
  - Maps to: a ruling card's default, undo and risk, kept as a record.
- **LLM Council.** Karpathy, A., 22 November 2025, "a fun Saturday hack".
  Several models answer, rank each other's answers anonymously, and a
  chairman model writes the final one. Models are set in `backend/config.py`.
  [github.com](https://github.com/karpathy/llm-council)
  - Maps to: a second agent as a way to verify. Here the chairman is the
    human, and the council only advises.
- **Perplexity Model Council.** Perplexity, 5 February 2026 (press coverage;
  the post's own date unverified). Three models answer one question and a
  synthesiser shows where they agree and where they differ.
  [perplexity.ai](https://www.perplexity.ai/hub/blog/introducing-model-council)
  - Maps to: the confer. Disagreement is surfaced for the human, not voted
    away.
