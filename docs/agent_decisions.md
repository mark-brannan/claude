# Agent decisions

Append-only. Each entry is a call an agent made in pencil: a default it took
under the one-way-door test, with its undo. Written by `agent-decision`; the
heading is the UTC stamp, so `agent_decisions.md#<stamp>` links one entry.

### 20261004t002454z
- Each repo keeps its own docs/agent_decisions.md, written in the PR that makes the call; the claude repo's starts here. Undo: move the entries to one repo. ([#33](https://github.com/mark-brannan/claude/pull/33))
- A curia's copy is <curia>/agent_decisions.md, the same name as the repo file. Undo: rename it. ([#33](https://github.com/mark-brannan/claude/pull/33))
- The trigger is a hand-over line in rules/code.md, not a skill, so every PR session sees it. Undo: revert that line. ([#33](https://github.com/mark-brannan/claude/pull/33))
- Calls in the same second share one heading, as roll.md's words do. Undo: one heading per call. ([#33](https://github.com/mark-brannan/claude/pull/33))

### 20261004t004955z
- docs/agent_decisions.md merges as union, and agent-decision adds that .gitattributes line to any repo it writes in, so parallel PRs that each append an entry rebase without a conflict. Undo: drop the line and ensure_union(). ([#33](https://github.com/mark-brannan/claude/pull/33))

### 20261004t021019z
- prune-worktrees waits 24h of HEAD/reflog idleness before a worktree is eligible Undo: change --hours default in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))
- prune-worktrees lets ignored files (node_modules, dist, settings.local.json) go with a removed worktree Undo: add an ignored-files keep rule ([#34](https://github.com/mark-brannan/claude/pull/34))
- stale worktrees are pruned by a daily 04:30 systemd timer, not the Stop hook Undo: disable prune-worktrees.timer ([#34](https://github.com/mark-brannan/claude/pull/34))

### 20261004t021506z
- prune-worktrees keeps metadata for a missing worktree whose parent directory is also missing (read as an unmounted disk), locking it across the prune Undo: drop prune_metadata's spare list in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))
- prune-worktrees force-removes a worktree with submodules when no submodule holds a commit on none of its remotes, rather than always keeping it Undo: keep every submodule worktree in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))

### 20261004t035542z
- stop-continuity spec: Evidence is one column with three values (test / code / item N), not a Source and Test split Undo: a doc PR splitting the column (mark-brannan/claude#36)
- stop-continuity spec: a Then may hold several assertions behind ';', and 'or' in a Given is two fixtures sharing the Then Undo: split the rows (mark-brannan/claude#36)
- stop-continuity spec: sections 1 to 13 are facts about the bash until the Python replaces it; section 14 holds while its ruling does; a disagreement goes to the curia, never to the spec Undo: edit the preamble (mark-brannan/claude#36)

### 20261004t035750z
- work-item create: a replay of one create (same id, same content) prints the same id and exits 0 instead of being refused; the pen line says a second write of the same id is refused, and a replay is read as the one write landing twice, not a second write Undo: delete replayed() in bin/work-item and refuse on every FileExistsError ([#37](https://github.com/mark-brannan/claude/pull/37))

### 20261004t052037z
- stop-item: a minted item stays open, never ready; the hook writes no status line after create Undo: log a later status from the step ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a minted item's brief is written once, at the mint: the prompt's first line plus one link line, never rewritten Undo: rewrite brief_for in hooks/stop-item.py ([#42](https://github.com/mark-brannan/claude/pull/42))

### 20261004t052038z
- stop-item: an item's home= is the session's PR when one exists Undo: drop the home= words ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: with no PR yet, a minted item's link is the session's checkpoint log: its GitHub URL, or a link relative to the item when the state repo has no GitHub origin Undo: change checkpoint_link ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a session that mints and then claims another item writes later Stops onto the claimed one Undo: reorder find_item ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a minted item's owner is agent Undo: change --owner in step() ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: the hook writes onto an item only when the PR changed; a claimed item gets one stop line, at the session's first Stop Undo: write every Stop ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a claimed item's home= is written only while it has none, so a card homed on an issue keeps it Undo: always write it ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a minted item's id is the session's start second plus its id8, so every Stop finds it without a pointer file Undo: a marker line instead ([#42](https://github.com/mark-brannan/claude/pull/42))
- stop-item: a crash or refusal fails open: exit 0, and the pickup file and the state commit still land Undo: revert the merge ([#42](https://github.com/mark-brannan/claude/pull/42))

### 20261004t033255z
- A grind item's hard cap, its worker's --max-budget-usd, is 3x its soft cap. Undo: change the 3 in grind's item_hard ([#47](https://github.com/mark-brannan/claude/pull/47))
- grind's run hard budget defaults to 1.5x --session-budget ($30 at the $20 default). Undo: change the 1.5 where grind defaults session_hard_budget ([#47](https://github.com/mark-brannan/claude/pull/47))
- A pr item's soft cap is not scaled by model or effort: the fixup contract's stop is a flat ~$1 every fixup worker reads. Undo: scale the pr branch of item_soft_cap like the others ([#47](https://github.com/mark-brannan/claude/pull/47))
- grind reads a card's budget= off its log lines itself; work-item fold does not carry it, its facts being the format ruled in pen. Undo: add budget to work-item's FACTS and read it from fold ([#47](https://github.com/mark-brannan/claude/pull/47))

### 20261004t050721z
- grind: an item's hard cap is 3x its soft cap, never cut by what the run has left, and the run hard budget (--session-hard-budget, 1.5x) is gone -- Solace's ruling on #47: soft stops, not hard ones; a worker is ended only three times past the stop it was told; more cautious hard stops are a later revisit. Supersedes the 1.5x entry above. Undo: revert the commit on #47 that removed session_hard_budget from bin/grind ([#47](https://github.com/mark-brannan/claude/pull/47))

### 20261004t071038z
- work-item read_brief turns CRLF into a newline before checking, so a brief piped with Windows line endings is accepted as on main; a lone CR is still refused Undo: revert d935ba0 ([#39](https://github.com/mark-brannan/claude/pull/39))

### 20261004t072330z
- Shared helpers named lib/lock.py and lib/gitrun.py Undo: git mv both modules and update the six importers and INSTALL ([#40](https://github.com/mark-brannan/claude/pull/40))
- bin/prune-worktrees keeps its own git runner; gitrun.run takes no env= or input= Undo: add env= and input= to gitrun.run and repoint prune-worktrees ([#40](https://github.com/mark-brannan/claude/pull/40))

### 20261004t075427z
- prune-worktrees finds lib/gitrun.py with sys.path.insert(0, ...), the same as prose-budget, github-limits and agent-decision, not the append a reviewer suggested Undo: switch all four tools to sys.path.append in one PR ([#50](https://github.com/mark-brannan/claude/pull/50))

### 20261004t082808z
- A cloud-session release is named by both seed SHAs plus a checksum of $HOME and the state repo's path, since Localise writes both into it. Undo: drop the third part of REV and guards_sha's second-field parse in cloud-session-setup.sh ([#54](https://github.com/mark-brannan/claude/pull/54))

### 20261004t082051z
- Keep the absolute /home/solace/.claude/bin/work-item rule beside the ~ one: a rule matches the command as typed, and agents sometimes type the expanded path; the private line does not treat a username as private. Undo: delete the absolute work-item line from settings.json ([#52](https://github.com/mark-brannan/claude/pull/52))

### 20261004t074915z
- grind's stop snapshot commit skips git hooks: unfinished work, not a change for hooks to judge. Undo: drop --no-verify in save_attempt ([#51](https://github.com/mark-brannan/claude/pull/51))
- A grind retry resumes from local tracking refs only and fetches nothing; other machines are out of scope for now. Undo: fetch the wip ref in resume_point ([#51](https://github.com/mark-brannan/claude/pull/51))
- grind leaves a wip ref in place after its item is done; a reopened issue would resume from the old snapshot. Undo: delete the resumed wip ref on done ([#51](https://github.com/mark-brannan/claude/pull/51))

### 20261004t083549z
- grind's stop snapshot holds back new files shaped like secrets (.env, .env.*, secrets/, *.pem, *.key, *.p12, *.pfx, id_rsa*/id_ecdsa*/id_ed25519*, .netrc, .npmrc, .pypirc, credentials.json); the retry does not get them Undo: drop the exclude pathspecs in save_attempt ([#51](https://github.com/mark-brannan/claude/pull/51))
- A non-PR grind retry is cut from the saved tip on its old base even when main has moved; the worker merges or rebases Undo: rebase the resumed tip onto HEAD in resume_point's caller ([#51](https://github.com/mark-brannan/claude/pull/51))

### 20261004t090521z
- grind's held-back shapes match in any case and add .env*, .aws/, .docker/config.json, keystores (jks, keystore, ppk, p8), id_dsa*, .git-credentials, .pgpass, .htpasswd, kubeconfig, credentials files, *secret*.json, service-account*.json, *.tfvars, terraform.tfstate* Undo: drop those pathspecs or the icase magic in save_attempt ([#55](https://github.com/mark-brannan/claude/pull/55))

### 20261007t005156z
- Stop block notice also carries the » metrics block, not just crossings and the verdict Undo: revert the fall-through in metrics-live.sh's Stop branch ([#61](https://github.com/mark-brannan/claude/pull/61))

### 20261007t032620z
- A ruling /sweep records privately goes to state/global/log/<date>-sweep-<project>.md, mirroring the agora sitting's log name Undo: rename the path in skills/agora/SKILL.md 'Where a ruling lands' ([#60](https://github.com/mark-brannan/claude/pull/60))
- A public ruling keeps the old home: the project's primary repo's docs/decisions.md (project-<name> topic, else the card's repo), not the repo whose issue argued it Undo: say 'that repo's docs/decisions.md' in skills/agora/SKILL.md 'Where a ruling lands' ([#60](https://github.com/mark-brannan/claude/pull/60))

### 20261007t044618z
- grind's stop save points the wip ref at the stop's tip even when the worker already pushed it, and may rewrite that ref under a lease pinned to the sha this checkout last saw, so a rebased tip replaces the last snapshot Undo: drop --force-with-lease in save_attempt ([#57](https://github.com/mark-brannan/claude/pull/57))

### 20261007t051846z
- curia: The decision is the only part of a Design section that must trace to a decided.md line; what hurt, the cost to change and open are the agent's reading Undo: restore 'every design sentence has a ledger line' in skills/curia/SKILL.md and template.md ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: close synthesizes every ruling landed since the last close, not only this sitting's; lint flags an uncarried ledger line only when it is older than the last words Where this stands cites Undo: revert the Closing step 1 and lint clauses in skills/curia/SKILL.md ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: close shows the diff of the rewritten Design sections for the user's redline; a section heading is the record's words, never a coined name; a pencil stamp under Rulings carries a gloss of what it holds Undo: delete the three clauses in skills/curia/SKILL.md and template.md ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: whether a noun gets a spec row stays open in template.md's Vocabulary comment, per a curia ledger line of 2026-10-07, rather than ruled no Undo: restore 'a noun gets no spec of its own' in template.md ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: the three callers that read rulings from digest.md's Decided (scoping's curia row, settledness rubric row 9 and its read-set) point at decided.md in this PR, not a follow-up Undo: revert the three one-line edits in skills/scoping and skills/doc-settledness-check ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: adr: in the digest header holds one link per promoted Design section Undo: restore the singular adr: field in template.md ([#64](https://github.com/mark-brannan/claude/pull/64))

### 20261007t051847z
- curia: sidecar names are working-backwards.md, scenarios.md, mvp-and-narrative.md, success-metric.md; problem-then-solution adds no sidecar Undo: rename in forms/*.md and SKILL.md ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: the ledger's seed is forms/decided.md; a pre-split digest's Decided moves whole to decided.md in lint's patch at its next opening Undo: delete forms/decided.md; drop the lint migration clause ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: a promoted Design section leaves one line linking its ADR; Where this stands shows Position and Size in place of Next; a dropped form's sidecar leaves the folder, git keeps it Undo: revert those lines in SKILL.md and template.md ([#64](https://github.com/mark-brannan/claude/pull/64))

### 20261007t071933z
- Past the spend line the hand-off file may be Read as well as Written: the Write tool refuses to overwrite a file not yet read, and a retried item has the last hand-off on disk Undo: drop Read from the exemption in hooks/spend-gate.py and the settings.json fallback ([#71](https://github.com/mark-brannan/claude/pull/71))

### 20261007t093718z
- Disable only the mergify-stack skill via a permissions.deny Skill(mergify:mergify-stack) rule, keep the plugin on Undo: remove the one deny line in settings.json ([#76](https://github.com/mark-brannan/claude/pull/76))

### 20261007t094943z
- curia: lint's uncarried-ledger-line check counts The problem and Vocabulary as carrying, exempts Superseded, and dates a line that cites no roll stamp by its date Undo: restore 'no Design section carries' in skills/curia/SKILL.md Opening step 3 ([#64](https://github.com/mark-brannan/claude/pull/64))
- curia: #64 keeps the opening lint, close-time synthesis in the sitting and the X-of-Y position that the 2026-10-07 pen rulings retire; #77 replaces them, so #64 flags them and lands only with #77 straight after Undo: port #77's opening, facets and Where-this-stands into #64 and rebase #77 ([#64](https://github.com/mark-brannan/claude/pull/64))

### 20261007t100254z
- curia: the no-private-stamp ruling is read to cover a skill's pen/pencil comments as well as specs and decisions logs, since a stamp there is provenance in prose; a spec row cites its repo's public decisions line, and the ledger line links the row Undo: restore the roll stamps in the two pencil comments; reword the spec-row sentence in SKILL.md Layers ([#64](https://github.com/mark-brannan/claude/pull/64))

### 20261007t102521z
- curia: the three facets run inside one background sub-agent in sequence, lint then edit then status, each starting after the previous commit, so no two write digest.md at once; the runner tells each facet how it was started Undo: restore three parallel spawns in SKILL.md Facets and Closing step 2 ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: lint marks a line it promotes to pen as 'pen (lint, <date>)' and lists it in its findings, rather than making the promotion a finding for the user Undo: make the pencil-to-pen move a finding only, in facets/lint.md and the queue table ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: edit decomposes a split only when started by hand or at close, never from a routine, and only on a pen line the user made; the user's hand in digest.md is a commit authored by the user with no Co-Authored-By: Claude trailer Undo: drop the routine clause and the trailer test in facets/edit.md steps 2 and 4 ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: status takes the words read at open from the spawning sitting and falls back to wc -w marked 'now' by hand or from a routine; the public decisions log gets its own read-from entry pointing at a line of its own Undo: restore wc -w only in facets/status.md; drop the decisions-log sentence under Prune what agents load ([#77](https://github.com/mark-brannan/claude/pull/77))

### 20261007t102629z
- curia: a facet commits its own mechanical fixes instead of handing a patch to a caller, since a background facet has no caller left to apply one Undo: restore the patch-under-inputs clause in facets/lint.md ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: the digest header field is named read-from: and lint is what moves it; decided.md takes none, since it prunes by moving lines out Undo: drop the header line from skills/curia/template.md ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: the queue table's Superseded row joins the trial's Superseded group to the proposal's deleted: moves there, deleted at the next prune Undo: pick one in the SKILL.md queue table ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: Working memory's cap is 750 words in place of 60 lines; facet prompts live under facets/, not forms/; Where this stands gains The one big thing in place of Position Undo: restore the line count, move the prompts, restore Position ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: the status figure for context at first question comes from the spawning sitting's transcript, or the session's metrics row by hand Undo: drop the row from facets/status.md ([#77](https://github.com/mark-brannan/claude/pull/77))

### 20261007t104154z
- curia: scoping's lock records decided.md, the file every ruling lands in, so a ruling landing only in the ledger mid-scoping trips the read-moved guard; skill text, not a bin/scoping-lock change Undo: say digest.md again in skills/scoping/SKILL.md §2 ([#64](https://github.com/mark-brannan/claude/pull/64))

### 20261007t105037z
- Branch-vs-main rule: 'GitHub can't answer' means an error or no token; an empty ruleset list is an answer Undo: revert 6c7669a ([#67](https://github.com/mark-brannan/claude/pull/67))

### 20261007t115240z
- AGPL 'or later' rather than 'only' for the code Undo: change the SPDX id in README.md and CITATION.cff to AGPL-3.0-only ([#80](https://github.com/mark-brannan/claude/pull/80))

### 20261007t115241z
- Split by file type: every Markdown file is CC BY-SA 4.0, all other files are AGPL Undo: edit the README License section ([#80](https://github.com/mark-brannan/claude/pull/80))
- Copyright holder 'Solace (Mark) Brannan' (the git identity); requested credit 'Solace Brannan' Undo: edit the README License section and CITATION.cff ([#80](https://github.com/mark-brannan/claude/pull/80))
- Add CITATION.cff so GitHub shows 'Cite this repository' Undo: delete CITATION.cff ([#80](https://github.com/mark-brannan/claude/pull/80))

### 20261007t114607z
- curia: a read-from: line of none, or none at all, means the file's first stamp; lint writes that stamp Undo: drop the none clause in facets/lint.md and SKILL.md Prune what agents load ([#77](https://github.com/mark-brannan/claude/pull/77))
- curia: every facet commit and every sitting commit to the state repo ends with the Co-Authored-By: Claude trailer; an untrailered digest line not clearly the user's is a finding, not pen Undo: drop the trailer line from the three facets and SKILL.md During ([#77](https://github.com/mark-brannan/claude/pull/77))

### 20261007t121138z
- Drop date-released from CITATION.cff: the repo has no release, and the date was the first commit's Undo: re-add date-released once a release is tagged ([#80](https://github.com/mark-brannan/claude/pull/80))

### 20261007t104505z
- Standing-orders guard line: prose names the remedy and points at the guard (editor's note on #70) Undo: drop the line's last sentence and say 'hook' for 'guard' in CLAUDE.md's guard line ([#70](https://github.com/mark-brannan/claude/pull/70))

### 20261007t120710z
- Standing-orders already-ruled line names no file, so it survives retirement (the user's altitude ruling on #70); keeps 'any exit' so omit is checked too Undo: restore 'the rules files, the repo's decisions file' in CLAUDE.md's already-ruled line ([#70](https://github.com/mark-brannan/claude/pull/70))

### 20261007t202646z
- references.md: mechanisms get their own section, not entries under The order Undo: move the four entries under The order ([#84](https://github.com/mark-brannan/claude/pull/84))

### 20261007t222710z
- A cloud-session release is named <claude sha>-<checksum> and .sync-status.json drops guards_sha, now that dotfiles no longer feeds the release Undo: restore GUARDS_REV in REV and the guards_sha field in cloud-session-setup.sh ([#83](https://github.com/mark-brannan/claude/pull/83))
- With the five guard copies gone, a machine without the languette plugin runs none of those gates; the copies' fail-closed fallback is not replaced Undo: add a settings.json PreToolUse tripwire that denies when the languette plugin is not installed ([#83](https://github.com/mark-brannan/claude/pull/83))

### 20261007t210740z
- work-item: a claim is valid from any status, open included (the user's ruling) Undo: one row edit in docs/work-item-lifecycle.md and the open -> claimed edge removed from ALLOWED ([#82](https://github.com/mark-brannan/claude/pull/82))
- work-item: the one-hour claim lapse is measured on the holder's newest line on the item, not its metrics record, until the hook keeps that line fresh (card 1791375174218fc901) Undo: fold reads the holder's live metrics record ([#82](https://github.com/mark-brannan/claude/pull/82))

### 20261008t190245z
- critical-review's summary mirrors the PR body's Pencil list under its own heading, kind first, kept by silence Undo: delete the Pencil heading from the skill; the PR body's list stays the only home

### 20261008t190246z
- the churn-ok label is a click line under Decide, with no default, undo or risk Undo: drop the click line; the red churn check says it
- a Decide line is posted as a PR thread first; the thread is its home Undo: let a Decide line stand on the summary alone
- a Look at item never carries a question Undo: revert the sentence

### 20261008t191213z
- Ruled by Solace 2026-10-08: churn-ok is never a Decide line and never discussed; the churn guard is the agent's toil, a red check means a smaller change. Bot threads walk the same exits; one at exit 4 stays open as the Decide line; one answered with a default is a Pencil line with the thread link Undo: reinstate the click line ([#100](https://github.com/mark-brannan/claude/pull/100))

### 20261008t192058z
- critical-review's summary opens with one line: what the PR does and whether it is ready, the sentence that stands in for reading the diff Undo: delete the opening-line sentence from the skill ([#100](https://github.com/mark-brannan/claude/pull/100))
### 20261008t031812z
- reconcile checks at most 50 linked cards per run, drawn at random, skipping briefs already prefixed Done/Ruled Undo: change or drop the cap paragraph in skills/reconcile/SKILL.md ([#536](https://github.com/mark-brannan/dotfiles/pull/536))
