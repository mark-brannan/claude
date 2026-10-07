# Work items: the spec

The rulings of the one-entry-point curia on the work item, one row each.
The curia governed them; the rows below are what the code follows, and a
disagreement between a row and the code is the code's bug, not the row's.
`work-item` enforces the transitions and the refusals named in the last
column, nothing more: the user dislikes validation past what a ruling asks
for.

Each row names its standing (pen: settled, build on it; pencil: provisional;
unmarked: ruled without a mark) and its evidence: the curia's digest section
and the roll stamp, as plain text. This repo does not link into the private
state repo. Once this repo has a `docs/decisions.md`, a row cites its line
there instead, and the stamps retire from this file.

## The item

| Rule | Standing | Code |
|---|---|---|
| There is one noun, the work item. Pickup file, hand-off and card are facets of it, and every loop-one path (pickup, grind, scoping and orchestrate, a free prompt) touches the same item | pen, 2026-10-03, §2, 20261003t223834z | `work-item`; `state/global/pickup/` retires once the Stop hook writes items |
| A curia is a specialized work item: the item is the family, card and curia its facets, curia the one with its own interaction model and name | pen, 2026-10-01, §2, 20261001t031157z | the curia skill keeps its own folder |
| The item is a brief plus a log, one file per item, the id its filename, at `state/global/items/<id>.md`. The name "item" is the description; the name of the thing stays pencil | pen, 2026-10-01, §2, 20261001t181542z | `work-item create` |
| The brief is the current "what to do next", rewritten rarely and only by the holder. On a human-owned item it carries the user's words verbatim; when the owner is an agent and the status is ready, the brief is the hand-off | pen, 2026-10-01, §2, 20261001t181542z | `work-item brief` |
| The brief is written with the card by the session that found the loop, never at the agora's admission; a create whose brief carries no link is refused | unmarked, 2026-10-03, §2, 20261003t025038z; the link rule is kanban-lint's L6 | `work-item create` refuses a brief with no http link or `owner/repo#n` |
| The log is append-only, one line per touch: timestamp, session, `key=value` facts; every state fact is last-one-wins; no header, no cached fields; views fold from it | pen, 2026-10-01, §2, 20261001t181542z | `work-item log`, `work-item show` |
| A `briefed` line, no text, is required whenever the brief changes; git holds the versions | pen, 2026-10-01, §2, 20261001t181542z | `work-item brief` writes it |
| Card and brief are one thing seen two ways: the card is the one line a view shows, the brief its body and one home | unmarked, 2026-10-03, §2, 20261003t023059z | views |
| The item drives difficulty, never the run: `model=` and `effort=` are facts of the item, and the runner reads them; grind's own flags are deprecated at once | pen, 2026-10-01, §2, 20261001t030100z, 20261001t031843z | `work-item create` takes `--model` and `--effort` |
| A hand-off is content a session leaves for its successor, in either loop, not a mechanism; the record must show whether it was taken up | unmarked, 2026-09-29, §2, 20260929t172849z | the claim line on the log |
| Every session creates its item at its first Stop, erring toward not losing the trail; the sweep that prunes old cards prunes the orphans too | pen, 2026-10-03, §2, 20261003t225525z | the Stop hook |
| The ad-hoc item for direct-prompt work that ends in a PR is written by the Stop hook at the first stop, reusing today's hand-off; its home is the PR, by `home=` | pencil, 2026-10-03, §2, 20261003t204910z | the Stop hook |
| The Stop hook's move into the item store is incremental: the git-risky core stays (WIP salvage, push lock, debounced push, metrics); one `work-item` call replaces the pickup file, the claim stamp, the checkpoint copy and the curia floor block | pen, 2026-10-03, §2, 20261003t230933z | the Stop hook, in progress |

**Flagged.** One pen line of 2026-10-01 (20261001t030100z) says the item's
shape, fields and home are open in the curia; the lines of the same day and
after (20261001t181542z, 20261001t213901z) ruled them. The later lines stand
and the earlier clause is stale; the curia's lint found it (2026-10-03,
2026-10-07) and no ruling has retired it yet.

## The identifier

| Rule | Standing | Code |
|---|---|---|
| The id is epoch seconds then the creating session's eight hex, no separator (`1790836842077c62eb`), created by the agent at write time, fire and forget, never edited, never reused | pen, 2026-10-01, §2, 20261001t064716z | `card-id`, `work-item create` |
| A second create in the same session-second is the design, not a hole: the id is idempotent, and a second write of the same id is refused by the store, never retried with a fresh id | pen, 2026-10-01, §2, 20261001t172704z | `work-item create` refuses an existing id |
| One id for the item's whole life: the sessions that touch it are listed on it in order, and the Stop hook updates the item it touched instead of writing one per session | pen, 2026-10-01, §2, 20261001t064716z | the log |
| The id is the Identifier layer; the file path, shard and board line are Data and may change under it | pen, 2026-10-01, §2, 20261001t064716z | — |
| The id is opaque and the file is the lookup: nothing parses the id; the date is the create line's timestamp, the title the brief's first line, the link the `home=` fact; no slug, no alias | pen, 2026-10-01, §2, 20261001t213901z | `work-item show` |
| A GitHub-homed item has two identities, both real; ours is not exposed externally, "at least for now", and no comment, label or body text on GitHub carries our id | pen, 2026-10-02, §2, 20261002t002558z | nothing writes the id to GitHub |
| The work item itself is the alias: `home=<owner/repo#n>` in its log, and the reverse lookup is a grep over the item files while the store stays modest | pen, 2026-10-02, §2, 20261002t002558z | `grep home= state/global/items/` |
| Mint, minted, minting are never a state or an identifier in code; prose may say it, code says create, and the first log line is `status=open` | pen, 2026-10-02, §2, 20261002t010422z | `work-item create` |

**Flagged.** "No alias" (20261001t213901z) and "the item itself is the
alias" (20261002t002558z) are both pen. The reading the code follows: no
second identifier is created for an item, and the `home=` fact already on
the log is how a GitHub reference resolves to one. The curia lists the pair
as open; the rows above stand on that reading until it rules.

## Statuses, transitions and claims

| Rule | Standing | Code |
|---|---|---|
| Six statuses: open, ready, claimed, blocked, done, closed. One second attribute, the owner: human-ruling, human-click or agent. An item is created open, always | pen, 2026-10-02, §2, 20261002t012203z | `work-item create` writes `status=open` |
| Transitions: open → ready; ready → claimed; claimed → blocked, ready, done; blocked → claimed, ready; done → claimed or ready; done → closed by acceptance only, never on a clock; closed → claimed; never claimed from open | pen, 2026-10-02, §2, 20261002t012203z | `work-item log` refuses any other step |
| Every work item is claimable, cards included: the claim extends to every home an item can have | pen, 2026-10-01, §2, 20261001t014929z | `work-item claim` |
| A claim is valid from ready, blocked, done or closed, the four sources the transitions row allows, and never while another session holds it; the ruling's own words name ready and closed, and the stale-claim rule is the agent's toil | pen, 2026-10-02, §2, 20261002t012203z | `work-item claim` refuses a held item and any other source |
| A claim lapses once the claiming session has been silent one hour since its last Stop, read from its metrics record; a new claim then takes over and logs the old session id; a resumed session re-claims. Measured over 137 session records: median 0.36 h, p90 1.07 h, none past two hours | pen, 2026-10-04, §2, 20261004t075633z | `work-item claim` |
| A session checks the claim at start and again before the real work | pen, 2026-10-01, §2, 20261001t181542z | the skills |
| "Pickup" is the verb, claim and read; the hand-off is a state of the brief, not a kind of item | pen, 2026-10-01, §2, 20261001t181542z | `pickup-list take` |
| The card claim and the one-writer lock are the agent's to build; the user is shown the data format of each | pen, 2026-10-01, §2, 20261001t021650z | `work-item` holds a per-item lock while writing |
| Done is the holder's word, with evidence; closed is acceptance, never silence; the archive window counts from closed, never from done | pen, 2026-10-02, §2, 20261002t011351z | `work-item log` refuses `status=done` with no `evidence=` |
| `closed` carries a reason, GitHub's shape and GitHub's words: `reason=completed` is done-done by acceptance, `reason=not-planned` is scope ruled out; `duplicate` and `reopened` are known too. The reason word is not validated | pen, 2026-10-04, §2, 20261004t073024z, 20261004t074317z | the reason is the ruling's; `work-item log` refuses every `closed` today (next row) |
| A ruling that closes a PR or cuts scope retires the cards carrying that scope in the same step: the sitting shows the cards, closes each whose whole brief is the cut scope and rewrites the brief of one that carries more; the roll stamp is the evidence; undo is closed → claimed | pen, 2026-10-04, §2, 20261004t072820z | the agora |
| Close, then archive, then delete, each after a window, never keeping indefinitely; the windows are the research's to propose, and keeping is the default until the research and monitoring exist | pen, 2026-10-02, §2, 20261002t004851z | nothing archives yet |
| A parent goes done and holds for closed, with a lint over the whole tree at parent-done and acceptance by agent and user at done → closed | pencil, 2026-10-02, §2, 20261002t012203z | `work-item log` refuses every `status=closed`, parent or not, until the whole-tree sweep exists; nothing writes `closed` today |
| What counts as acceptance, the acceptance period and the sweep's mechanics | open: "We can figure that out later" | — |

### Each ending, as the skills write it (pencil, the agent's reading)

| Ending | Sequence | Written by |
|---|---|---|
| Agent work lands | claim → `done evidence=<PR>` | the worker |
| A ruling, made in agora | claim → `done evidence=<roll or decisions line>` | agora, in the ruling's turn |
| Click work the user confirms | claim → `done evidence=<their words>` | card-helper, in the confirming turn |
| Stale, moot or ruled elsewhere | claim → `done evidence=<why moot>` | sweep, on the user's tick; reconcile |
| A runner retires a card | claim → `done evidence=<PR>` | the runner |

## The board and views

| Rule | Standing | Code |
|---|---|---|
| The board stops being a hand-edited file: kanban.md goes, views fold from `state/global/items/`. "I do not want a single file where sessions contend with one another" | pen, 2026-10-03, §2, 20261003t025038z | `worklist`, `pickup-list` |
| The board's home is settled; its data structure is a directory: recency, stack or queue and other priorities are derived as needed | unmarked, 2026-10-03, §2, scoping proposal of 2026-10-03 | the items directory |
| The board and the state repo stay markdown-in-git; measure, don't migrate, with ceilings of pack size 500 MiB and the hour of the next push throttle | unmarked, 2026-09-29, §2, 20260929t080053z | — |
| Awake / asleep replaces the sweep tick dialog, on condition that the counts (total, awake, asleep, by bucket and tag) are always shown and every count has a drill path | unmarked, 2026-09-28, §1, digest-at-cut §5 | `worklist` |
| One writer puts every worker-raised question on the board under Needs ruling; no separate questions file | pen, 2026-10-01, §1, 20261001t020530z | the runner |
| Scoping's in-flight step reads each open PR against the decided ledger: a PR whose scope a ruling closed gets the verdict "contradicts", with the ruling linked, in place of "in flight" | pen, 2026-10-04, §2, 20261004t075633z | the scoping skill |
| The "mechanics only" order in the kanban-to-items plan is suspect: "I do not recognize or understand what we mean" | unmarked, 2026-10-03, §2, scoping proposal of 2026-10-03 | — |
| `worklist` keeps its name and roughly its shape: the combined list, lanes by owner; `grind --dry-run` keeps its own name for now, converging later | pen, 2026-10-01, §2, 20261001t015941z; unmarked, 2026-09-28, digest-at-cut §5 | `worklist` |

## Hooks and telemetry

| Rule | Standing | Code |
|---|---|---|
| Telemetry is produced by the system, for what matters; owned, ours. Reverse-engineering a number from git's records after the fact is not it | unmarked, 2026-09-29, §5, 20260929t080200z | the metrics hooks |
| The decision-count nag goes everywhere, not only in a curia: the count stays a number to track and to want, and never nudges toward a stop, in any session | pen, 2026-09-30, §5, 20260930t233614z | the Stop hook |
| Friction is the hook's one alarm, for now; the decisions-to-clock ratio is measured, not alarmed, and behaviour change stays the agent's to notice in the dialogue | pen, 2026-09-30, §5, 20260930t234019z | the Stop hook |
| The ratio is shown in two places, never the statusline: the session-start "Decision load, last 7 days" block and the session-end summary | unmarked, 2026-10-01, §5, 20261001t005252z | SessionStart and Stop hooks |
| The friction rule stands as is: three corrections or rebukes in twenty turns, retuned only after the decision-count nags are gone and friction is the sole alarm firing | unmarked, 2026-10-01, §5, 20261001t005516z | the Stop hook |

## Vocabulary

The words the rows above use, with the ruling behind each. Names the curia
refused are in its agent notes, one line, not here.

| Word | Means | Standing |
|---|---|---|
| work item | a brief plus a log, one file per item, its id the filename; card and curia are its facets | pen, 20261001t181542z, 20261003t223834z; the thing's name is pencil |
| brief | the item's current "what to do next", rewritten rarely, by the holder; the user's words verbatim on a human-owned item | pen, 20261001t181542z |
| log | append-only, one line per touch, `key=value` facts, the last one wins; every view folds from it | pen, 20261001t181542z |
| card | the one line a view shows for an item; the brief is its body. The word is kept; its semantics and data structure stayed open in the curia | pen, 20261001t020118z; unmarked, 20261003t023059z |
| board | the view folded from `state/global/items/`; kanban.md goes. If the item family had been threads the word would be trail, a mixed desk | pen, 20261001t020118z, 20261003t025038z; unmarked, digest-at-cut §5 |
| bucket | a lane of the board by owner: Needs ruling, the user's click work, the agent's queue | pen, 20261001t020118z |
| item id | epoch seconds then the creating session's eight hex; opaque, never parsed, never reused | pen, 20261001t064716z, 20261001t213901z |
| pickup | the verb: claim an item and read it | pen, 20261001t181542z |
| claim | a session's hold on an item; valid from ready or closed, lapsing an hour after the holder's last Stop | pen, 20261002t012203z, 20261004t075633z |
| owner | human-ruling, human-click or agent: who the item exists for | pen, 20261002t012203z |
| toil and judgment | an assessment, made when the item is created, of why it exists for a human, an agent, or between. The words are pen; the concept is incomplete | pen, 20260929t093409z |
| agora | the quick sitting: rulings in batch, each with a default that holds; where a Needs ruling card is answered | pen, digest-at-cut §5 |
| worklist | the combined list, lanes by owner; the name and roughly the shape kept | pen, 20261001t015941z |
| ready, blocked, awaiting-human, salvage ref, band | the mechanical labels and refs: low priority, easy to evolve, not a key design question | unmarked, digest-at-cut §5 |
| create | what code says where prose says mint | pen, 20261002t010422z |
