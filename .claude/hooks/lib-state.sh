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
#   ahead <n>     an upstream exists; n commits are not on it (n may be 0)
#   unknown       an upstream exists, but the count could not be taken
#   never-pushed  no upstream, and there is work on the branch to lose
#   safe          no upstream, but nothing on the branch to lose
#
# The last two are the carve-outs. A detached HEAD whose commit already lives
# on some remote branch is not a hazard (#128/#143), and a named branch with
# no upstream is not one either until it is actually ahead of the default
# branch (#126) -- the same test branch-home-gate.sh applies before it looks
# for a home. `rev-list @{u}..HEAD` fails outright when there is no upstream,
# and the `|| echo 0` that used to swallow that read a never-pushed branch as
# fully pushed: the "lost work" failure one step earlier than #108/#110.
unpushed_state() {
  local root="$1" branch="$2" n base ahead

  if git -C "$root" rev-parse --verify -q --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    n=$(git -C "$root" rev-list --count '@{u}..HEAD' 2>/dev/null || printf '')
    [ -n "$n" ] && printf 'ahead %s' "$n" || printf 'unknown'
    return 0
  fi

  if [ "$branch" = HEAD ] || [ -z "$branch" ]; then
    [ -n "$(git -C "$root" branch -r --contains HEAD 2>/dev/null)" ] \
      && printf 'safe' || printf 'never-pushed'
    return 0
  fi

  base=$(git -C "$root" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)
  base="${base:-origin/main}"
  git -C "$root" rev-parse --verify -q "$base" >/dev/null 2>&1 || base=origin/master
  ahead=$(git -C "$root" rev-list --count "$base..HEAD" 2>/dev/null || printf 0)
  [ "${ahead:-0}" -gt 0 ] && printf 'never-pushed' || printf 'safe'
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
