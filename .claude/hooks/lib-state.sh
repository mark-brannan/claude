#!/usr/bin/env bash
# Shared helpers for the continuity hooks. Sourced, never run directly.
#
# The one job here is answering "where does durable state live on this
# machine?" without any hook having to guess. Every hook that writes state
# calls state_dir; every hook that reads it calls the same function, so a
# machine where the private repo is missing degrades identically everywhere
# instead of one hook writing to the repo and another to a local fallback.

# Resolve the private state repo's working tree, or empty if it isn't here.
#
# Order matters: an explicit env var wins, then the paths a cloud session
# checks out a source repo to, then the paths a real machine clones to.
# No cloning is attempted -- a SessionStart hook that clones a private repo
# would need credentials it cannot count on, and would stall session start
# on a network round trip. Absence is reported, not repaired.
state_repo() {
  local d
  for d in "${CLAUDE_STATE_REPO:-}" \
           /home/user/claude_prompts_scratch \
           /workspace/claude_prompts_scratch \
           "$HOME/claude_prompts_scratch" \
           "$HOME/src/claude_prompts_scratch" \
           "$HOME/Projects/claude_prompts_scratch" \
           "$HOME/code/claude_prompts_scratch"; do
    [ -n "$d" ] && [ -d "$d/.git" ] && { printf '%s' "$d"; return 0; }
  done
  return 1
}

# Directory that state files are written under, always. Falls back to a
# local, gitignored directory so a machine without the repo still keeps its
# own copy rather than silently dropping every line.
state_dir() {
  local repo
  if repo=$(state_repo); then
    printf '%s/state/global' "$repo"
  else
    printf '%s/.claude/state/global' "$HOME"
  fi
}

# True when state_dir is inside the git repo, i.e. worth committing.
state_is_repo() { state_repo >/dev/null 2>&1; }

# True when $1 appears as a whole branch-name token in text on stdin -- not
# merely as a substring. `-w` alone is not enough: branch names are built
# from hyphens too, so claude/homed-extra is a `-w` match for claude/homed.
# Extract every maximal run of branch-name characters and require one to
# equal the branch exactly. The charset is deliberately narrower than every
# character git allows in a branch name (no `~^:?*[\`, no non-ASCII): it
# exists to strip prose punctuation (a trailing period or comma) off a
# branch mention in a sentence, and `+`/`@` are the two git allows that
# never show up as that kind of padding. Shared by branch-home-gate.sh and
# worklist so a branch counts as pointed-at the same way in both.
names_branch() {
  grep -oE '[A-Za-z0-9._/+@-]+' | grep -qxF -- "$1"
}

# One JSON-string escaper for the hooks that source this. It takes its text as
# an argument, and falls back to sed/awk where jq is absent -- a hook that
# cannot emit its reason is a hook that fails open. Do not add a second
# json_str with a different signature: kanban-gate.sh once sourced this file
# and then shadowed it, and the two disagreed about stdin vs "$1".
json_str() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -Rs .
  else
    printf '"%s"\n' "$(printf '%s' "$1" | tr '\t' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{ if (NR > 1) printf "\\n"; printf "%s", $0 }')"
  fi
}
block() { printf '{"decision":"block","reason":%s}\n' "$(json_str "$1")"; exit 0; }

# The set of tool calls that change git state, in one place.
#
# It lives here because three consumers have to agree on it: the PostToolUse
# matcher in settings.json, metrics-live.sh's "is this worth recomputing"
# filter, and measure-git-events.sh's pre-filter. When they disagreed the
# narrow one won by accident -- a `git push`, a `git reset`, a `git branch
# -D`, an MCP `push_files` or a `merge_pull_request` each changed the repo
# and none of them moved a counter until the Stop hook swept the transcript
# at the end of the session. A number that only becomes true afterwards is
# not a live number, and the git block the user actually reads never appeared at
# the moment the state changed.
#
# Deliberately NOT here: `git add`, `fetch`, `clone`, `remote`, `status`,
# `log`, `diff`. The first four are frequent and carry no decision; the rest
# are reads. Every entry costs a full jq pass over the transcript, so the
# line is drawn at "did the repo's history, refs or worktree move".
#
# Two shapes are matched: a shell command (Bash tool_input.command) and a
# bare tool name (any MCP tool that writes a repo, branch or PR).
git_event_re() {
  printf '%s' '\bgit\s+(commit|push|pull|merge|rebase|cherry-pick|revert|checkout|switch|branch|worktree|tag|stash|reset|restore|rm|mv|apply|am)\b|\bgh\s+(pr|release)\b|\b(yadm|dotsync)\b|create_pull_request|merge_pull_request|update_pull_request|update_pull_request_branch|push_files|create_or_update_file|delete_file|create_branch|create_repository|fork_repository'
}

# Answer "does this branch hold commits that exist nowhere but here?" for a
# repo root ($1) and the branch name ($2, `HEAD` or empty when detached).
#
# It lives here because two hooks have to agree on the answer: metrics-live.sh
# draws the ⎇ nag and the archival verdict from it, stop-continuity.sh's
# set_verdict decides from it whether the session is safe to kill. When each
# had its own copy they drifted -- #148 had to port two carve-outs back into
# metrics-live.sh that stop-continuity.sh had grown in #126 and #128/#143.
#
# Prints one word, plus a count for the first:
#   ahead <n>     an upstream exists; n commits are on no origin branch (n may be 0)
#   unknown       the count could not be taken
#   never-pushed  no upstream, and there are commits on no origin branch
#   safe          no upstream, but every commit already lives on an origin branch
#
# The count is `HEAD --not --remotes=origin`, never `@{u}..HEAD`: `mergify
# stack push` leaves @{u} at origin/main while the commits go to a differently
# named stack/ branch, so the upstream diff called pushed work unpushed. A
# detached HEAD or a fresh branch with no upstream falls out of the same test.
# `origin/wip/*` is excluded: those are the Stop hook's salvage refs, pushed
# before this verdict is taken, and salvage is not publication -- counting
# them read every salvaged branch as pushed. No origin refs at all reads safe.
unpushed_state() {
  local root="$1" n

  # No origin refs at all (no remote, never fetched): nothing to be ahead of.
  [ -n "$(git -C "$root" for-each-ref --count=1 refs/remotes/origin 2>/dev/null)" ] \
    || { printf 'safe'; return 0; }
  n=$(git -C "$root" rev-list --count HEAD --not --exclude='origin/wip/*' --remotes=origin 2>/dev/null || printf '')
  [ -n "$n" ] || { printf 'unknown'; return 0; }
  if git -C "$root" rev-parse --verify -q --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    printf 'ahead %s' "$n"
  elif [ "$n" -gt 0 ]; then
    printf 'never-pushed'
  else
    printf 'safe'
  fi
}

# archivable_reasons <work_root> <work_branch> [<session-id>] -- the reasons
# a session on this branch is not yet archivable, comma-joined; empty when
# it is. Order: worktree dirty, unpushed commits, branch home, session live.
#
# Lives here for the same reason unpushed_state does: metrics-live.sh's live
# nag and stop-continuity.sh's Stop-hook verdict must never disagree about
# what "archivable" means (dotfiles#149). Before this they didn't even
# agree on what a "home" is -- metrics-live.sh re-checked PR-or-kanban
# inline and never looked for a pointer issue, the one branch-home-gate.sh
# already finds.
#
# Requires $HOOK_DIR set by the caller: branch-home-gate.sh and
# claim-stamp.sh live beside this file and are shelled out to, not sourced,
# so their own state (branch-home-gate.sh's once-per-session gate,
# claim-stamp.sh's per-session record) never leaks into this read-only check.
#
# Home is checked before session-live, and both only when dirty/unpushed are
# already clean: both can shell out to `gh` (branch-home-gate.sh up to two
# 30s calls, claim-stamp.sh one), so a dirty mid-work tree -- the common
# case, and the one Stop fires on every turn -- never pays that cost.
# Restores the short-circuit the pre-dotfiles#149 archivable() had.
#
# session live (dotfiles#167): git state alone is how a live session's
# worktree got archived out from under it (PR #162, the scar
# no-foreign-worktree.sh names). The signal is the claim stamp
# claim-stamp.sh already posts on the branch's card and refreshes on every
# Stop (dotfiles#287); it, not this function, decides fresh vs stale
# (CLAIM_STALE_SECS). <session-id> is the caller's own: its own stamp is
# never a reason, or a session could never become archivable by watching
# its own refresh. Omit it (a sweep, a human) and every fresh stamp counts.
#
# Not this function's job: "not a git repo" (there is no branch here to
# judge) and anything that only becomes true after a push is attempted --
# both are the caller's own facts to add.
archivable_reasons() {
  local work_root="$1" work_branch="$2" self_sid="${3:-}" reasons="" home ust self8
  add_reason() { reasons="${reasons:+$reasons, }$1"; }

  [ -z "$(git -C "$work_root" status --porcelain 2>/dev/null)" ] || add_reason "worktree dirty"

  ust=$(unpushed_state "$work_root" "$work_branch")
  case "$ust" in
    'ahead 0')   ;;
    'ahead '*)   add_reason "${ust#ahead } commit(s) unpushed" ;;
    unknown)     add_reason "could not count unpushed commits" ;;
    never-pushed)
      if [ "$work_branch" = HEAD ] || [ -z "$work_branch" ]; then
        add_reason "detached HEAD, no upstream to compare against"
      else
        add_reason "\`$work_branch\` has no upstream (never pushed)"
      fi
      ;;
  esac

  if [ -z "$reasons" ]; then
    home=$(sh "$HOOK_DIR/branch-home-gate.sh" --check "$work_root" 2>/dev/null)
    # Handed back through a file, never a variable: every caller runs this
    # function inside $(...), where a variable dies with the subshell.
    # stop-continuity.sh's pickup item wants the same home line and must
    # not pay branch-home-gate.sh's gh round trip a second time in one Stop.
    [ -z "${ARCHIVABLE_HOME_FILE:-}" ] \
      || printf '%s\n' "$home" > "$ARCHIVABLE_HOME_FILE" 2>/dev/null
    case "$home" in
      home:*)       : ;;
      unverified:*) add_reason "branch home unverified (${home#unverified: })" ;;
      *)            add_reason "no PR and no pointer for \`$work_branch\`" ;;
    esac
  fi

  if [ -z "$reasons" ] && [ -x "$HOOK_DIR/claim-stamp.sh" ]; then
    self8=$(printf '%s' "$self_sid" | cut -c1-8)
    if sh "$HOOK_DIR/claim-stamp.sh" read -C "$work_root" 2>/dev/null \
         | awk -F'\t' -v s="$self8" '$1 == "live" && $2 != s { found = 1 } END { exit !found }'; then
      add_reason "session live"
    fi
  fi

  printf '%s' "$reasons"
}

# state_lock <dir> / state_unlock -- mkdir atomic test-and-set, copied from
# grind's per-repo lock (no flock: macOS has none). meta carries pid+host; a
# same-host dead pid is reclaimed via rename-then-rm. Installs no trap of its
# own: `trap` overwrites rather than chains, and a caller (stop-continuity.sh
# already arms one, e.g. `trap restore_board EXIT`) would have it silently
# clobbered. The caller adds `state_unlock` to its own EXIT/TERM/INT traps.
# A dir with no meta at all (a kill between mkdir and the meta write) has no
# pid to check; one older than STATE_LOCK_STALE_SECS is reclaimed regardless
# -- no `stat` (flags differ GNU/BSD), so age comes from `-ot` against a
# reference file touched to the cutoff.
STATE_LOCK_DIR=""
STATE_LOCK_STALE_SECS="${STATE_LOCK_STALE_SECS:-5}"

state_lock() {
  local dir="$1" meta="" host pid ref cutoff rc
  [ -n "$dir" ] || return 1
  meta="$dir/meta"
  host=$(uname -n 2>/dev/null || echo unknown)
  if ! mkdir "$dir" 2>/dev/null; then
    if [ -f "$meta" ]; then
      pid=$(awk -F= '$1 == "pid" { print $2 }' "$meta" 2>/dev/null)
      { [ "$(awk -F= '$1 == "hostname" { print $2 }' "$meta" 2>/dev/null)" = "$host" ] \
          && [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; } || return 1
    else
      ref="$dir.age.$$"; cutoff=$(( $(date +%s) - STATE_LOCK_STALE_SECS ))
      if ! { : > "$ref" 2>/dev/null && touch -t "$(date -d "@$cutoff" +%Y%m%d%H%M.%S 2>/dev/null \
        || date -r "$cutoff" +%Y%m%d%H%M.%S)" "$ref" 2>/dev/null; }; then
        rm -f "$ref"; return 1
      fi
      [ "$dir" -ot "$ref" ]; rc=$?; rm -f "$ref"; [ "$rc" -eq 0 ] || return 1
    fi
    mv "$dir" "$dir.stale.$$" 2>/dev/null && rm -rf "$dir.stale.$$" && mkdir "$dir" 2>/dev/null \
      || return 1
  fi
  printf 'pid=%s\nhostname=%s\n' "$$" "$host" > "$meta" 2>/dev/null
  STATE_LOCK_DIR="$dir"
}

state_unlock() {
  [ -n "$STATE_LOCK_DIR" ] && rm -rf "$STATE_LOCK_DIR"
  STATE_LOCK_DIR=""
}

# state_lock_wait <dir> <secs> -- state_lock, retried once a second for up to
# <secs>: the portable `flock -w`. A bare `flock` here silently exited every
# Stop hook on macOS before the state-repo push.
# shellcheck disable=SC2034 # read by stop-continuity.sh and abandon-branch.sh
STATE_PUSH_LOCK="${TMPDIR:-/tmp}/claude-state-push.lock.d"
state_lock_wait() {
  local dir="$1" n="${2:-90}"
  until state_lock "$dir"; do
    [ "$n" -gt 0 ] || return 1
    n=$((n - 1)); sleep 1
  done
}

# day_decisions <sid> <total> <junk> <now> <gap-seconds> -- fold this session's
# decision counts into the machine-wide store beside sitting.json and print the
# day's totals as "<total>\t<junk>". Decision load is spent across a day, not
# per chat (#99); a prompt gap past <gap-seconds> anywhere on the machine starts
# a fresh day. Keyed by session id, holding each session's own running counts
# rather than a delta, so a replayed hook cannot double-count. junk rides beside
# the total, never subtracted -- exclude it by subtracting field two. No trap
# here: it would clobber the caller's (#361).
day_decisions() {
  local f next
  f="$(state_dir)/metrics/day-decisions.json"
  mkdir -p "${f%/*}" 2>/dev/null || { printf '0\t0\n'; return 0; }
  if state_lock "$f.lock"; then
    # Read, modify and write all inside the lock -- a read before it is the race
    # the lock closes: a second session's write in between would be overwritten.
    [ -f "$f" ] || printf '{}\n' > "$f" 2>/dev/null
    next=$(jq --arg sid "$1" --argjson t "$2" --argjson j "$3" \
      --argjson now "$4" --argjson gap "$5" \
      'if (.last_prompt // 0) > 0 and ($now - .last_prompt) > $gap
       then {day_start: $now, sessions: {}} else . end
       | .last_prompt = $now | .day_start //= $now
       | .sessions[$sid] = {total: $t, junk: $j}' "$f" 2>/dev/null)
    if [ -n "$next" ] && printf '%s\n' "$next" > "$f.$$" 2>/dev/null \
       && mv -f "$f.$$" "$f" 2>/dev/null; then :; else rm -f "$f.$$" 2>/dev/null; fi
    state_unlock
  fi
  jq -r '[([.sessions[]?.total] | add // 0), ([.sessions[]?.junk] | add // 0)] | @tsv' "$f" 2>/dev/null || printf '0\t0\n'
}

# decision_rate <decisions> <span-seconds> -- "<n> decisions in 1h10 (2.6/h)",
# or nothing when the session clock (first prompt to last) is under a minute.
# Measured, never alarmed (one-entry-point §5, 2026-09-30): the two places that
# call it are the session-start brief and the Stop checkpoint, nothing else.
decision_rate() {
  awk -v d="${1:-0}" -v s="${2:-0}" 'BEGIN {
    if (s < 60) exit
    m = int(s / 60 + 0.5)
    printf "%d decision%s in %dh%02d (%.1f/h)\n", d, (d == 1 ? "" : "s"), int(m / 60), m % 60, d * 3600 / s
  }'
}

# pr_base_refs <repo-path> <branch> [<remote>] -- base branch names of the
# open PRs whose head is <branch>, one per line.
#
# Empty output with status 0 means "no open PR"; non-zero means the lookup
# could not be made at all (no gh, no such remote, gh failed). Those are
# different answers and flattening them into each other is how a stacked PR
# gets silently rebased onto main -- resign-branch.sh's header argues it at
# length. Policy on 0/1/many stays with the caller, which is why this
# function has none; resign-branch.sh adopts it in a later PR (dotfiles#266,
# churn guard).
pr_base_refs() {
  local url out
  command -v gh >/dev/null 2>&1 || return 1
  url=$(git -C "$1" remote get-url "${3:-origin}" 2>/dev/null) || return 1
  out=$(gh pr list -R "$url" --head "$2" --state open \
          --json baseRefName --jq '.[].baseRefName' 2>/dev/null) || return 1
  printf '%s' "$out"
}

# default_branch <repo-path> [<remote>] -- the remote's default branch, short
# name, or non-zero when this clone has never recorded one. Read-only by
# contract: no `git remote set-head`, so a caller that wants the write has to
# make it itself.
default_branch() {
  local r="${2:-origin}" ref
  ref=$(git -C "$1" symbolic-ref -q --short "refs/remotes/$r/HEAD" 2>/dev/null) || return 1
  printf '%s' "${ref#"$r/"}"
}

# branch_brief <repo-path> <branch> -- the facts a session starting on an
# existing branch keeps getting wrong, one per line, ending in exactly one
# recommended command. Read-only: it never fetches, commits or pushes.
#
# It exists because those facts already lived in four places and consumers
# re-derived them badly anyway (#206, #185): no-unsigned-push.sh owns the
# unsigned test, resign-branch.sh the PR-base lookup, this file
# unpushed_state, /pickup step 3 the checkout rules. One printer, one answer,
# and consumers stop deriving.
#
# Lines: worktrees, base, ahead, behind, conflicts, unsigned, merges,
# recommend. A fact that cannot be taken prints `unknown` rather than a
# guess -- read-only means no fetch, so a base ref this machine has never
# fetched is genuinely not known here, and saying "0 behind" would be a lie
# in the direction that loses work.
#
# `unsigned` is the presence of a `gpgsig` header, which is the test
# no-unsigned-push.sh makes and not `%G?`: on a machine with no
# allowed-signers file -- every cloud VM -- `%G?` reports every signed commit
# unverified, so a brief built on it would demand a resign on a branch that
# is already fine.
#
# Worktrees holding the branch are reported, not judged. Whether the session
# that holds one is still alive is dotfiles#167.
#
# The recommendation ladder is ordered by what is unrecoverable, not by what
# is common, and follows code.md's "Green before it is handed over":
# merge commits outrank everything (a rebase drops whatever lives only in a
# hand-resolved merge's tree), then conflicts, then signing, then the plain
# rebase that a clean branch wants.
branch_brief() {
  local root="$1" br="$2" bases nb base wts lr ahead behind conf revs uns mg mb
  _bb() { git -C "$root" "$@"; }

  _bb rev-parse --verify -q "refs/heads/$br" >/dev/null 2>&1 \
    || { printf 'error: no branch %s in %s\n' "$br" "$root"; return 1; }

  wts=$(_bb worktree list --porcelain \
          | awk -v b="branch refs/heads/$br" '/^worktree /{p=substr($0,10)} $0==b{print p}' \
          | tr '\n' ' ')
  printf 'worktrees: %s\n' "${wts:-none}"

  if bases=$(pr_base_refs "$root" "$br"); then
    nb=$(printf '%s' "$bases" | grep -c . || true)
  else
    nb=unknown
  fi
  base=""
  case "$nb" in
    1) base=$bases; printf 'base: %s (open PR)\n' "$base" ;;
    0) base=$(default_branch "$root") || base=""
       printf 'base: %s (default branch, no open PR)\n' "${base:-unknown}" ;;
    unknown)
       base=$(default_branch "$root") || base=""
       printf 'base: %s (assumed: the open-PR lookup failed, so a stacked base would not show)\n' "${base:-unknown}" ;;
    *) printf 'base: ambiguous -- %s open PRs, bases: %s\n' \
              "$nb" "$(printf '%s' "$bases" | tr '\n' ' ')" ;;
  esac

  if [ -z "$base" ] || ! _bb rev-parse --verify -q "origin/$base" >/dev/null 2>&1; then
    printf 'ahead: unknown\nbehind: unknown\nconflicts: unknown\nunsigned: unknown\nmerges: unknown\n'
    printf 'recommend: no base to compare against here -- `git fetch origin` and re-run, or name the base by hand\n'
    return 0
  fi

  if lr=$(_bb rev-list --left-right --count "origin/$base...$br" 2>/dev/null); then
    behind=${lr%%[!0-9]*}
    ahead=${lr##*[!0-9]}
  else
    ahead=unknown; behind=unknown
  fi
  printf 'ahead: %s\nbehind: %s\n' "$ahead" "$behind"

  # merge-tree returns 0 clean, 1 conflicted, and something else for any
  # other failure -- a git too old for --write-tree included. Reading every
  # non-zero as "conflicted" would recommend a merge commit onto a branch
  # that does not need one.
  if _bb merge-tree --write-tree "origin/$base" "$br" >/dev/null 2>&1; then
    conf=no
  else
    case $? in 1) conf=yes ;; *) conf=unknown ;; esac
  fi

  if revs=$(_bb rev-list "origin/$base..$br" 2>/dev/null); then
    uns=$(printf '%s\n' "$revs" | while read -r s; do
            [ -n "$s" ] || continue
            _bb cat-file -p "$s" | grep -q '^gpgsig' || printf 'x\n'
          done | grep -c . || true)
  else
    uns=unknown
  fi
  mg=$(_bb rev-list --count --merges "origin/$base..$br" 2>/dev/null) || mg=unknown
  printf 'conflicts: %s\nunsigned: %s\nmerges: %s\n' "$conf" "$uns" "$mg"

  mb=$(_bb merge-base "origin/$base" "$br" 2>/dev/null || printf '%s' "origin/$base")
  if [ "$mg" = unknown ]; then
    printf 'recommend: count the merge commits by hand before touching history -- git could not count them between %s and origin/%s\n' "$br" "$base"
  elif [ "$mg" -gt 0 ]; then
    printf 'recommend: do not rebase and do not resign -- %s merge commit(s) on the branch; `git merge origin/%s`, resolve, commit signed, push as a fast-forward\n' "$mg" "$base"
  elif [ "$conf" = yes ]; then
    printf 'recommend: git merge origin/%s   # conflicts against the base; resolve, commit, and never linearize the branch afterwards\n' "$base"
  elif [ "$conf" = unknown ]; then
    printf 'recommend: check the merge by hand before touching history -- git merge-tree could not answer whether %s conflicts with origin/%s\n' "$br" "$base"
  elif [ "$uns" = unknown ]; then
    printf 'recommend: check the signatures by hand before pushing -- git could not list the commits between origin/%s and %s\n' "$base" "$br"
  elif [ "$uns" -gt 0 ] && _bb config user.signingkey >/dev/null 2>&1; then
    printf 'recommend: git rebase -S --force-rebase %s   # %s unsigned commit(s); if %s is already on the remote, resign-branch.sh %s instead\n' "$mb" "$uns" "$br" "$br"
  elif [ "$uns" -gt 0 ]; then
    printf 'recommend: cannot sign on this machine (no user.signingkey) -- %s unsigned commit(s) will block the PR; hand over saying resign-branch.sh %s has to run where the key is\n' "$uns" "$br"
  else
    printf 'recommend: git fetch origin %s && git rebase origin/%s\n' "$base" "$base"
  fi
}

# ------------------------------------------------------------- units of work
# A pickup item and a card on the board's `## Claude's` are facets of one
# thing, the unit of work and of continuity between sessions (one-entry-point
# curia, Solace, 2026-10-01). Until they are one record on disk they are one
# record on read: every view that lists work reads it through work_record, so
# pickup-list, worklist's resume section and /pickup cannot disagree about
# what an item is.

# work_record <pickup-file | card-text> [<updated>] -- one unit of work as one
# line, fields separated by \037 (a tab would be collapsed by `read`):
#
#   kind title status until claim model effort link id updated
#
# kind is `pickup` or `card`. An absent field is empty; the renderer draws
# the dash. A pickup item's model, effort, until and link come from its
# hand-off body, so the model is the previous session's recommendation; the
# header's model (the session that wrote it) stands in only when the body
# names none. A card's come from its own `model:`, `effort:`, `until:` fields
# and its first link; its id is its `id:` field (the link on a card minted
# before ids), and a claim on it is keyed by that link. A card's <updated> is the caller's to
# pass (claude_cards takes it from git blame); its status is `taken` while a
# live claim stands, and claim is the holder's short session id.
work_record() {
  if [ -f "$1" ]; then work_records "$1"
  else printf '%s\t%s\n' "${2:-}" "$1" | work_records --cards; fi
}

# work_records [--cards] [<pickup-file>...] -- work_record for many, in one
# awk pass: a listing of two hundred items cannot afford a dozen forks each.
# --cards reads `<updated>\t<card text>` lines (claude_cards' output) from
# stdin first. Claims come from $WORK_CLAIMS when the caller primed it with
# work_claims_load (one read for a whole listing), else are read here.
work_records() {
  if [ "${1:-}" = --cards ]; then shift; set -- cards=1 - cards=0 "$@"; fi
  [ $# -gt 0 ] || return 0
  [ -n "${WORK_CLAIMS+x}" ] || work_claims_load
  WORK_CLAIMS=$WORK_CLAIMS awk '
    BEGIN {
      US = "\037"
      n = split(ENVIRON["WORK_CLAIMS"], L, "\n")
      for (i = 1; i <= n; i++) {
        split(L[i], c, "\t")
        if (c[1] == "live" && c[5] != "" && !(c[5] in held)) held[c[5]] = c[2]
      }
    }
    function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t\r]+$/, "", s); return s }
    function mshort(m) {
      m = tolower(m)
      if (m ~ /fable/) return "fable"; if (m ~ /opus/) return "opus"
      if (m ~ /sonnet/) return "sonnet"; if (m ~ /haiku/) return "haiku"
      if (m == "none" || m == "?" || m == "-") return ""
      return m
    }
    function emit(kind, title, st, until, claim, model, effort, link, id, up) {
      print kind US title US st US until US claim US mshort(model) US trim(effort) US link US id US up
    }
    # A card field: the value after " <name>:" up to ";", ")", the next field or the end.
    function cfield(b, k,   p, v) {
      b = " " b; p = index(b, " " k ":"); if (!p) p = index(b, "(" k ":"); if (!p) return ""
      v = substr(b, p + length(k) + 2); sub(/^[ \t]+/, "", v)
      if (match(v, /[;)]/)) v = substr(v, 1, RSTART - 1)
      if (match(v, / [a-z][a-z ]*:/)) v = substr(v, 1, RSTART - 1)
      return trim(v)
    }
    function card(up, b,   title, link, t, p, claim) {
      sub(/^[ \t]*(- \[[ xX]\] |- |[0-9]+\. )/, "", b)
      if (substr(b, 1, 2) == "**") {
        t = substr(b, 3); p = index(t, "**"); title = p ? substr(t, 1, p - 1) : t
      } else { title = b; gsub(/\]\([^)]*\)/, "", title); gsub(/\[/, "", title) }
      link = ""
      if (match(b, /\]\((https?:\/\/[^) ]+|(\.\.\/)*log\/[^) ]+)\)/)) link = substr(b, RSTART + 2, RLENGTH - 3)
      else if (match(b, /https?:\/\/[^ )>]+/)) link = substr(b, RSTART, RLENGTH)
      claim = (link in held) ? held[link] : ""
      emit("card", trim(title), claim != "" ? "taken" : "open", cfield(b, "until"), claim,
           cfield(b, "model"), cfield(b, "effort"), link, (cfield(b, "id") != "" ? cfield(b, "id") : link), up)
    }
    function bget(k) { return (k in bf) ? bf[k] : "" }
    function flushp(   id, model, link) {
      if (cur == "") return
      id = cur; sub(/^.*\//, "", id); sub(/\.md$/, "", id)
      model = bget("model"); if (model == "") model = hf["model"]
      link = bget("link"); if (link == "" && hf["pr"] != "none") link = hf["pr"]
      emit("pickup", title, hf["status"] == "" ? "open" : hf["status"], bget("until"), "",
           model, bget("effort"), link, id, hf["updated"])
      cur = ""
    }
    cards { p = index($0, "\t"); card(substr($0, 1, p - 1), substr($0, p + 1)); next }
    FNR == 1 { flushp(); cur = FILENAME; body = 0; title = ""; split("", hf); split("", bf) }
    !body && /^---$/ { body = 1; next }
    !body {
      p = index($0, ": ")
      if (p) { k = substr($0, 1, p - 1); if (!(k in hf)) hf[k] = trim(substr($0, p + 2)) }
      next
    }
    title == "" && /[^ \t\r]/ { title = trim($0); next }
    match($0, /^(until|effort|link|model):/) {
      k = substr($0, 1, RLENGTH - 1); if (!(k in bf)) bf[k] = trim(substr($0, RLENGTH + 1))
    }
    END { flushp() }
  ' "$@"
}

# work_claims_load -- set $WORK_CLAIMS to every card claim on record, one
# `live|stale <sid8> <machine> <age>m <url>` line each (claim-stamp.sh owns
# the ledger and its format). Empty when the claim script is not here.
work_claims_load() {
  local cs="${HOOK_DIR:-$HOME/.claude/hooks}/claim-stamp.sh"
  WORK_CLAIMS=""
  [ -f "$cs" ] && WORK_CLAIMS=$(sh "$cs" card-claims 2>/dev/null)
  return 0
}

# is_card_id <word> -- true for a work item's identifier: epoch seconds, then
# the minting session's eight hex, no separator (Solace, 2026-10-01).
is_card_id() {
  case "${1:-}" in *[!0-9a-f]*|'') return 1 ;; esac
  [ ${#1} -eq 18 ] && case "$1" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*) return 0 ;; esac
  return 1
}

# board_card <kanban.md> <id> -- the card whose `id:` is <id>, from any
# section, as `<section>\t<group>\t<folded card>`; fails when none is. The
# one lookup from an id back to the card's title, date and link. Matches the
# field the way kanban-lint's L11 does, so a card the lint passes is found.
board_card() {
  [ -f "$1" ] || return 1
  awk -v want="$2" '
    function flush() { if (txt != "" && txt ~ ("(^|[ (])id:[ \t]*" want "([^0-9a-z]|$)")) { print sec "\t" grp "\t" txt; hit = 1 } txt = "" }
    /^## /  { flush(); sec = substr($0, 4); grp = ""; next }
    /^### / { flush(); grp = substr($0, 5); next }
    /^#/ || /^[ \t]*$/ { flush(); next }
    /^(- |[0-9]+\. )/ { flush(); txt = $0; sub(/[ \t]+$/, "", txt); next }
    txt != "" { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t); txt = txt " " t }
    END { flush(); exit !hit }
  ' "$1"
}

# claude_cards <kanban.md> -- the pickup candidates on a board: every card
# under `## Claude's`, folded onto one line with its indented continuations,
# ticked lines skipped. One `<updated>\t<card text>` per card, <updated> the
# ISO time git blame gives the card's newest line, or empty off git.
# Only the agent's section: a ruling waits for the user and click work is
# theirs, so neither is work a session can pick up.
claude_cards() {
  local f="$1" times
  [ -f "$f" ] || return 0
  times=$(git -C "$(dirname "$f")" blame --line-porcelain -- "$(basename "$f")" 2>/dev/null \
    | awk '/^[0-9a-f]+ [0-9]+ [0-9]+/ { n = $3 } /^author-time / { print "@T " n " " $2 }')
  printf '%s\n' "$times" | awk '
    # days_to_civil (Howard Hinnant), so no date(1) call per card
    function iso(e,   z, era, doe, yoe, y, doy, mp, d, m, s) {
      if (e == "") return ""
      s = e % 86400; z = int(e / 86400) + 719468
      era = int(z / 146097); doe = z - era * 146097
      yoe = int((doe - int(doe / 1460) + int(doe / 36524) - int(doe / 146096)) / 365)
      y = yoe + era * 400; doy = doe - (365 * yoe + int(yoe / 4) - int(yoe / 100))
      mp = int((5 * doy + 2) / 153); d = doy - int((153 * mp + 2) / 5) + 1
      m = mp < 10 ? mp + 3 : mp - 9; if (m <= 2) y++
      return sprintf("%04d-%02d-%02dT%02d:%02d:%02dZ", y, m, d, int(s / 3600), int(s % 3600 / 60), s % 60)
    }
    function flush() { if (txt != "") print iso(newest) "\t" txt; txt = ""; newest = "" }
    function seen(n) { if ((n in at) && (newest == "" || at[n] > newest)) newest = at[n] }
    /^@T / { split($0, a, " "); at[a[2]] = a[3]; next }
    /^## /       { flush(); sec = ($0 ~ /^## Claude/); next }
    /^#/         { flush(); next }
    !sec         { next }
    /^[ \t]*$/   { flush(); next }
    /^- \[[xX]\]/ { flush(); skip = 1; next }
    /^(- |[0-9]+\. )/ { flush(); skip = 0; txt = $0; seen(FNR); next }
    txt != "" && !skip { t = $0; sub(/^[ \t]+/, "", t); txt = txt " " t; seen(FNR) }
    END { flush() }
  ' - "$f"
}

# --- Ruling-card readiness -------------------------------------------------------
# ruling_readiness <card text> -- prints `ready` or `waiting` for one
# ## Needs ruling card, its continuation lines already folded onto one line.
#
# Ruled by Solace, 2026-10-01 (one-entry-point curia, decided so far): a
# ruling card is ready when its `until:` date has arrived or the PR or issue
# it links is in flight, otherwise waiting -- kept, counted, hidden by
# default. `until:` holds a date, a PR/issue link, or an event in words; an
# event in words is waiting until a human says otherwise. Every date and
# every link in the value is read, and any one of them makes the card ready:
# a value like "2026-09-12, before 1.8" is a date that has a note on it.
#
# The rest is the agent's, pencil:
#   - in flight: a PR in any state (it exists, so the work started; merged or
#     closed is past due, and past due is shown), an issue that is closed, or
#     an open issue that an open PR closes. An open issue with no such PR is
#     waiting.
#   - no `until:` at all (a kind: tentative ADR card, a legacy card) is ready:
#     nothing names a condition to wait on. A link gh cannot answer for is
#     ready too. Showing a waiting card costs a line; hiding a ready one costs
#     the ruling.
#   - link state is cached under $XDG_CACHE_HOME/ruling-refs for
#     RULING_REF_TTL seconds (900). RULING_REF_CACHE_ONLY=1 never calls gh and
#     takes a stale entry over none -- worklist --brief sets it, because
#     SessionStart gives it seconds. RULING_TODAY overrides today's date.
ruling_until() {
  printf '%s\n' "$1" | awk '
    { l = tolower($0); p = index(l, "until:"); if (!p) exit 1
      v = substr($0, p + 6)
      if (match(tolower(v), /[ (;,.*](default|undo|risk|judgment|gates|settle|repos|repo|kind|why you|why this|id):/)) v = substr(v, 1, RSTART - 1)
      sub(/^[ \t*]+/, "", v); sub(/[ \t*.;,]+$/, "", v); print v; found = 1; exit }
    END { if (!found) exit 1 }'
}

# ruling_ref_state <owner> <repo> <number> -- pr-open | pr-merged | pr-closed |
# issue-open | issue-inflight | issue-closed, or unknown when neither the
# cache nor gh can say.
ruling_ref_state() {
  local dir f now line at st q
  dir="${XDG_CACHE_HOME:-$HOME/.cache}/ruling-refs"
  f="$dir/$1_$2_$3"
  now=$(date +%s)
  line=$(cat "$f" 2>/dev/null)
  at=${line%% *}; st=${line#* }
  if [ -n "$line" ] && { [ "${RULING_REF_CACHE_ONLY:-0}" = 1 ] \
       || [ $((now - at)) -lt "${RULING_REF_TTL:-900}" ]; }; then
    printf '%s' "$st"; return 0
  fi
  if [ "${RULING_REF_CACHE_ONLY:-0}" = 1 ] || ! command -v gh >/dev/null 2>&1; then
    printf 'unknown'; return 0
  fi
  # shellcheck disable=SC2016  # GraphQL variables, not shell
  q='query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){issueOrPullRequest(number:$n){
       __typename ... on PullRequest{state}
       ... on Issue{state closedByPullRequestsReferences(first:10,includeClosedPrs:false){nodes{state}}}}}}'
  set -- "$1" "$2" "$3" gh api graphql -F owner="$1" -F name="$2" -F n="$3" -f query="$q" --jq '
    .data.repository.issueOrPullRequest
    | if . == null then "unknown"
      elif .__typename == "PullRequest" then "pr-" + (.state | ascii_downcase)
      elif .state == "CLOSED" then "issue-closed"
      elif ([.closedByPullRequestsReferences.nodes[] | select(.state == "OPEN")] | length) > 0 then "issue-inflight"
      else "issue-open" end'
  shift 3
  command -v timeout >/dev/null 2>&1 && set -- timeout 10 "$@"
  st=$("$@" 2>/dev/null) || st=unknown
  case $st in
    pr-open|pr-merged|pr-closed|issue-open|issue-inflight|issue-closed)
      mkdir -p "$dir" 2>/dev/null && printf '%s %s\n' "$now" "$st" > "$f" 2>/dev/null ;;
    *) st=unknown ;;
  esac
  printf '%s' "$st"
}

ruling_readiness() {
  local v today d st
  v=$(ruling_until "$1") || { printf 'ready\n'; return 0; }
  today=${RULING_TODAY:-$(date +%Y-%m-%d)}
  for d in $(printf '%s\n' "$v" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}'); do
    # ISO dates sort as strings.
    if [ ! "$d" \> "$today" ]; then printf 'ready\n'; return 0; fi
  done
  # Links: a github.com PR/issue URL, or owner/repo#n. A bare #n names no repo
  # and reads as words.
  printf '%s\n' "$v" \
    | grep -oE 'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(pull|issues)/[0-9]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+' \
    | sed -E 's|^github\.com/||; s#/(pull|issues)/# #; s|#| |; s|/| |' \
    | { while read -r o r n; do
          st=$(ruling_ref_state "$o" "$r" "$n")
          [ "$st" = issue-open ] || { printf 'ready\n'; exit 0; }
        done; exit 1; } && return 0
  printf 'waiting\n'
}
