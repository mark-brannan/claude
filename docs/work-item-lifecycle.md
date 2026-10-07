# Work items: the spec

The rules the work item follows, one row each, and in the last column the
mechanism that enforces each. The rows lead the code: a disagreement between
a row and the code is the code's bug, not the row's. `work-item` enforces the
transitions and the refusals named here, nothing more: the user dislikes
validation past what a rule asks for.

The rulings behind the rows live in the curia that made them. Once this repo
has a `docs/decisions.md`, a row cites its line there.

## The item

| Rule | Code |
|---|---|
| There is one noun, the work item. Pickup file, hand-off and card are facets of it, and every loop-one path (pickup, grind, scoping and orchestrate, a free prompt) touches the same item | `work-item`; `state/global/pickup/` retires once the Stop hook writes items |
| A curia is a specialized work item: the item is the family, card and curia its facets, curia the one with its own interaction model and name | the curia skill keeps its own folder |
| The item is a brief plus a log, one file per item, the id its filename, at `state/global/items/<id>.md` | `work-item create` |
| The brief is the current "what to do next", rewritten rarely and only by the holder. On a human-owned item it carries the user's words verbatim; when the owner is an agent and the status is ready, the brief is the hand-off | `work-item brief` |
| The brief is written with the card by the session that found the loop, never at the agora's admission; a create whose brief carries no link is refused | `work-item create` refuses a brief with no http link or `owner/repo#n` (kanban-lint's L6) |
| The log is append-only, one line per touch: timestamp, session, `key=value` facts; every state fact is last-one-wins; no header, no cached fields; views fold from it | `work-item log`, `work-item show` |
| A `briefed` line, no text, is required whenever the brief changes; git holds the versions | `work-item brief` writes it |
| Card and brief are one thing seen two ways: the card is the one line a view shows, the brief its body and one home | views |
| The item drives difficulty, never the run: `model=` and `effort=` are facts of the item, and the runner reads them; grind's own flags are deprecated | `work-item create` takes `--model` and `--effort` |
| A hand-off is content a session leaves for its successor, in either loop, not a mechanism; the record must show whether it was taken up | the claim line on the log |
| Every session creates its item at its first Stop, erring toward not losing the trail; the sweep that prunes old cards prunes the orphans too | the Stop hook |
| The ad-hoc item for direct-prompt work that ends in a PR is written by the Stop hook at the first stop, reusing today's hand-off; its home is the PR, by `home=` | the Stop hook |
| The Stop hook's move into the item store is incremental: the git-risky core stays (WIP salvage, push lock, debounced push, metrics); one `work-item` call replaces the pickup file, the claim stamp, the checkpoint copy and the curia floor block | the Stop hook |

## The identifier

| Rule | Code |
|---|---|
| The id is epoch seconds then the creating session's eight hex, no separator (`1790836842077c62eb`), created by the agent at write time, fire and forget, never edited, never reused | `card-id`, `work-item create` |
| A second create in the same session-second is the design, not a hole: the id is idempotent, and a second write of the same id is refused by the store, never retried with a fresh id | `work-item create` refuses an existing id |
| One id for the item's whole life: the sessions that touch it are listed on it in order, and the Stop hook updates the item it touched instead of writing one per session | the log |
| The id is the Identifier layer; the file path, shard and board line are Data and may change under it | — |
| The id is opaque and the file is the lookup: nothing parses the id; the date is the create line's timestamp, the title the brief's first line, the link the `home=` fact; no slug, no second identifier | `work-item show` |
| A GitHub-homed item has two identities, both real; ours is not exposed externally for now, and no comment, label or body text on GitHub carries our id | nothing writes the id to GitHub |
| The work item itself is the alias: `home=<owner/repo#n>` in its log, and the reverse lookup is a grep over the item files while the store stays modest | `grep home= state/global/items/` |
| Mint, minted, minting are never a state or an identifier in code; prose may say it, code says create, and the first log line is `status=open` | `work-item create` |

## Statuses, transitions and claims

| Rule | Code |
|---|---|
| Six statuses: open, ready, claimed, blocked, done, closed. One second attribute, the owner: human-ruling, human-click or agent. An item is created open, always | `work-item create` writes `status=open` |
| Transitions: open → ready; ready → claimed; claimed → blocked, ready, done; blocked → claimed, ready; done → claimed or ready; done → closed by acceptance only, never on a clock; closed → claimed; never claimed from open | `work-item log` refuses any other step |
| Every work item is claimable, cards included: the claim extends to every home an item can have | `work-item claim` |
| A claim is valid from ready, blocked, done or closed, never open, and never while another session holds it; the stale-claim rule is the agent's toil | `work-item claim` refuses a held item and any other source |
| A claim lapses once the claiming session has been silent one hour since its last Stop; a new claim then takes over and logs the old session id; a resumed session re-claims. Measured over 137 session records: median 0.36 h, p90 1.07 h, none past two hours | `work-item claim`; the Stop hook writes a `stop` line on the held item |
| A session checks the claim at start and again before the real work | the skills |
| "Pickup" is the verb, claim and read; the hand-off is a state of the brief, not a kind of item | `pickup-list take` |
| The card claim and the one-writer lock are the agent's to build; the user is shown the data format of each | `work-item` holds a per-item lock while writing |
| Done is the holder's word, with evidence; closed is acceptance, never silence; the archive window counts from closed, never from done | `work-item log` refuses `status=done` with no `evidence=` |
| `closed` carries a reason, GitHub's shape and GitHub's words: `reason=completed` is done-done by acceptance, `reason=not-planned` is scope ruled out; `duplicate` and `reopened` are known too. The reason word is not validated | `work-item log` |
| A ruling that closes a PR or cuts scope retires the cards carrying that scope in the same step: the sitting shows the cards, closes each whose whole brief is the cut scope and rewrites the brief of one that carries more; the roll stamp is the evidence; undo is closed → claimed | the agora |
| Close, then archive, then delete, each after a window, never keeping indefinitely; the windows are the research's to propose, and keeping is the default until the research and monitoring exist | the sweep |
| A parent goes done and holds for closed, with a lint over the whole tree at parent-done and acceptance by agent and user at done → closed | the whole-tree sweep writes `closed`; `work-item log` refuses it from anything else |

Open: what counts as acceptance, the acceptance period and the sweep's
mechanics.

### Each ending, as the skills write it

| Ending | Sequence | Written by |
|---|---|---|
| Agent work lands | claim → `done evidence=<PR>` | the worker |
| A ruling, made in agora | claim → `done evidence=<roll or decisions line>` | agora, in the ruling's turn |
| Click work the user confirms | claim → `done evidence=<their words>` | card-helper, in the confirming turn |
| Stale, moot or ruled elsewhere | claim → `done evidence=<why moot>` | sweep, on the user's tick; reconcile |
| A runner retires a card | claim → `done evidence=<PR>` | the runner |

## The board and views

| Rule | Code |
|---|---|
| The board is not a hand-edited file where sessions contend with one another: kanban.md goes, views fold from `state/global/items/` | `worklist`, `pickup-list` |
| The board's home is settled; its data structure is a directory: recency, stack or queue and other priorities are derived as needed | the items directory |
| The board and the state repo stay markdown-in-git; measure, don't migrate, with ceilings of pack size 500 MiB and the hour of the next push throttle | — |
| Awake / asleep replaces the sweep tick dialog, on condition that the counts (total, awake, asleep, by bucket and tag) are always shown and every count has a drill path | `worklist` |
| One writer puts every worker-raised question on the board under Needs ruling; no separate questions file | the runner |
| Scoping's in-flight step reads each open PR against the decided ledger: a PR whose scope a ruling closed gets the verdict "contradicts", with the ruling linked, in place of "in flight" | the scoping skill |
| `worklist` keeps its name and roughly its shape: the combined list, lanes by owner; `grind --dry-run` keeps its own name for now, converging later | `worklist` |

## Hooks and telemetry

| Rule | Code |
|---|---|
| Telemetry is produced by the system, for what matters; owned, ours. Reverse-engineering a number from git's records after the fact is not it | the metrics hooks |
| The decision-count nag goes everywhere, not only in a curia: the count stays a number to track and to want, and never nudges toward a stop, in any session | the Stop hook |
| Friction is the hook's one alarm, for now; the decisions-to-clock ratio is measured, not alarmed, and behaviour change stays the agent's to notice in the dialogue | the Stop hook |
| The ratio is shown in two places, never the statusline: the session-start "Decision load, last 7 days" block and the session-end summary | SessionStart and Stop hooks |
| The friction rule stands as is: three corrections or rebukes in twenty turns, retuned only after the decision-count nags are gone and friction is the sole alarm firing | the Stop hook |

## Vocabulary

The words the rows above use. Names the curia refused are in its agent
notes, not here.

| Word | Means |
|---|---|
| work item | a brief plus a log, one file per item, its id the filename; card and curia are its facets |
| brief | the item's current "what to do next", rewritten rarely, by the holder; the user's words verbatim on a human-owned item |
| log | append-only, one line per touch, `key=value` facts, the last one wins; every view folds from it |
| card | the one line a view shows for an item; the brief is its body |
| board | the view folded from `state/global/items/`; kanban.md goes |
| bucket | a lane of the board by owner: Needs ruling, the user's click work, the agent's queue |
| item id | epoch seconds then the creating session's eight hex; opaque, never parsed, never reused |
| pickup | the verb: claim an item and read it |
| claim | a session's hold on an item; valid from ready, blocked, done or closed, never open, lapsing an hour after the holder's last Stop |
| owner | human-ruling, human-click or agent: who the item exists for |
| toil and judgment | an assessment, made when the item is created, of why it exists for a human, an agent, or between; the concept is incomplete |
| agora | the quick sitting: rulings in batch, each with a default that holds; where a Needs ruling card is answered |
| worklist | the combined list, lanes by owner; the name and roughly the shape kept |
| ready, blocked, awaiting-human, salvage ref, band | the mechanical labels and refs: low priority, easy to evolve, not a key design question |
| create | what code says where prose says mint |
