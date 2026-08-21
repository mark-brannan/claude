# Derives a session's cost and decision record from its transcript.
#
# Input : the transcript JSONL, slurped into an array (jq -s).
# Args  : $sid $repo $branch $cwd $now
# Output: one object {session: {...}, decisions: [...]}
#
# Everything here is read from records the harness already writes. Nothing
# depends on the assistant emitting a marker, which is exactly why the
# previous ⛁-marker hook logged nothing: a metric the measured party has to
# self-report is the first one to go quiet.

def lastline: split("\n") | map(select(test("\\S"))) | last // "";

# --- what counts as an ask ------------------------------------------------
# The original test -- last non-blank line ends in "?" -- misses the exact
# shape Mark asks for: a numbered escalation followed by a fenced block he
# can paste back. Three forms are accepted now:
#   trailing "?"          the turn stopped on a question
#   enumerated ask        "1." / "2." items, at least one of them a question
#   trailing fenced block stripped off, if what precedes it is either of the
#                         above -- the fence is the answer form, not the ask
def enum_items: split("\n") | map(select(test("^\\s*\\d+[.)]\\s+\\S")));

def is_ask:
  (lastline | test("\\?\\s*$"))
  or (((enum_items | length) >= 2) and (enum_items | any(test("\\?"))));

# The text before a trailing ``` fenced block, or null if there isn't one.
def prefence:
  (sub("\\s+$"; "")) as $t
  | if ($t | test("```\\s*$"))
    then ($t | split("```")) as $p
         | if ($p | length) >= 3 then ($p[0:-2] | join("```")) else null end
    else null end;

# The ask inside an assistant message, or null. Empty string is never an ask.
def ask_text:
  if (. == null or . == "") then null
  elif is_ask then .
  else (prefence // null) as $pre
       | if ($pre != null and ($pre | is_ask)) then $pre else null end
  end;

# A tool call that changes something. Used only to split "before work
# started" from "after", which is what separates a cheap scoping question
# from an expensive mid-flight one.
def mutating_bash:
  test("\\bgit\\s+(commit|push|merge|rebase|cherry-pick)\\b")
  or test("\\bsed\\s+-i\\b")
  or test("\\btee\\b")
  # a redirect to a real file, not to /dev/null and not 2>&1 -- without the
  # lookahead every read-only `... 2>/dev/null` counts as work having started,
  # which is how an obviously-scoping question gets filed as an expensive one
  or test(">>?\\s*(?!/dev/null)[^>|&\\s]");

def is_mutating:
  (.name | IN("Write","Edit","NotebookEdit"))
  or (.name == "Bash" and ((.input.command // "") | mutating_bash));

# Files a mutating Bash command writes to. Under auto mode nearly every edit
# is a heredoc, a `tee` or a `sed -i`, none of which produce a Write/Edit
# tool call -- so counting only those tools reports files_written: 0 for a
# session that rewrote half the repo.
def bash_targets:
  . as $c
  | [ ($c | [ match(">>?\\s*(?!/dev/null)([^>|&;()\\s]+)"; "g")
              | .captures[0].string ]),
      ($c | [ match("\\btee\\s+(?:-a\\s+)?([^>|&;()\\s]+)"; "g")
              | .captures[0].string ]),
      # sed -i [-e SCRIPT]... SCRIPT FILE
      ($c | [ match("\\bsed\\s+-i\\S*\\s+(?:-e\\s+\\S+\\s+)*(?:'[^']*'|\"[^\"]*\"|\\S+)\\s+([^>|&;()\\s]+)"; "g")
              | .captures[0].string ]) ]
  | add
  | map(select(. != null))
  | map(sub("^[\"']+"; "") | sub("[\"']+$"; ""))
  | map(select(. != "" and (startswith("-") | not)
               and (startswith("/dev/") | not)
               # scraping shell text is inherently approximate: require the
               # token to look like a path so `>= 2` inside a heredoc does
               # not get filed as a written file
               and test("[./]") and (test("^[0-9=]") | not)));

to_entries as $E

| ([ $E[].value | select(.type == "assistant") ]
   | group_by(.requestId // .uuid) | map(.[0])) as $amsgs

| [ $E[] | .key as $i | .value | select(.type == "assistant")
    | (.message.content[]? | select(.type == "tool_use")
       | {i: $i, name: .name, input: .input}) ] as $tools

| ([ $tools[] | select(is_mutating) | .i ] | min) as $first_mut_raw
| (($first_mut_raw // 999999999)) as $first_mut

# Human input, including messages injected mid-turn. Every message Mark
# sends is enqueued with its text; the `user` record for the first one is a
# duplicate of its enqueue, so counting enqueues avoids double-counting the
# opening prompt while still catching mid-turn interjections.
| [ $E[] | select(.value.type == "queue-operation"
                  and .value.operation == "enqueue"
                  and (.value.content // "") != "")
    | .key ] as $humans

# --- decisions -----------------------------------------------------------
# Two mechanisms, both mechanically detectable:
#   AskUserQuestion -- an explicit, structured hand-off
#   prose           -- the last assistant text before a human turn is an ask
#                      (see is_ask): a trailing question, an enumerated
#                      escalation, or either of those under a fenced block
| ([ $tools[] | select(.name == "AskUserQuestion")
     | {i: .i, mechanism: "AskUserQuestion",
        n: ((.input.questions // []) | length),
        text: ((.input.questions // []) | map(.question) | join(" | "))} ]
   +
   [ $humans[] | select(. > 0) as $h
     | ([ $E[] | select(.key < $h and .value.type == "assistant")
          | .value.message.content[]? | select(.type == "text")
          | .text ] | last // "" | ask_text) as $ask
     | select($ask != null)
     | { i: $h,
         mechanism: "prose",
         n: 1,
         # the last non-blank line of the ask is the readable summary; for an
         # enumerated escalation that is its final item, not the fence
         text: ($ask | lastline) } ]
   | sort_by(.i)) as $raw_decisions

| ([ $raw_decisions | to_entries[]
     | .key as $seq | .value
     | {ts: $now, session_id: $sid, repo: $repo, branch: $branch,
        seq: ($seq + 1),
        turn_index: .i,
        mechanism: .mechanism,
        questions: .n,
        before_first_write: (.i < $first_mut),
        # scoping  cheap: asked before any work exists to invalidate
        # inline   moderate: a bounded choice that blocks the current task
        # gate     expensive: open-ended or unstructured, mid-flight, and
        #          needs Mark to reload context he has not been carrying
        type: (if .i < $first_mut then "scoping"
               elif .mechanism == "prose" then "gate"
               elif .n > 2 then "gate"
               else "inline" end),
        question: (.text | .[0:300])} ]) as $decisions

# --- time ----------------------------------------------------------------
# Three numbers, because they answer different questions and no one of them
# substitutes for another:
#   elapsed  how long the chat has been open. Not "work" -- a 4h session with
#            a lunch in it reads 4h -- but it is the number that predicts
#            cost, because an old session re-sends a large context.
#   active   elapsed with every silence clamped to CAP. Walking away stops
#            the clock; thinking for a minute does not.
#   split    of that active time, which side was busy. The gap that ends in
#            Mark typing is his (reading, deciding); every other gap is the
#            agent's (thinking, tools, waiting on a command).
# Measured on eight sessions of this project, elapsed ran 5x active on the
# long one (270m vs 50m) and identical on the short ones -- the clamp only
# bites where someone left the room.
| def epoch: sub("\\.[0-9]+"; "") | fromdateiso8601;

  120 as $cap

| ([ $E[].value | select(.timestamp != null)
     | {t: (.timestamp | epoch),
        # only a human enqueue with text closes an idle gap as Mark's; the
        # duplicate `user` record for the opening prompt is skipped for the
        # same reason it is skipped when counting turns
        h: (.type == "queue-operation" and .operation == "enqueue"
            and ((.content // "") != ""))} ]
   | sort_by(.t)) as $ev

| (($ev | length) as $n
   | if $n > 1 then [ range(1; $n) | {d: ($ev[.].t - $ev[.-1].t), h: $ev[.].h} ]
     else [] end) as $gaps

| (if ($ev | length) > 1 then ($ev[-1].t - $ev[0].t) else 0 end
   | round) as $elapsed_s
| (([ $gaps[] | ([.d, $cap] | min) ] | add) // 0 | round) as $active_s
| (([ $gaps[] | select(.h) | ([.d, $cap] | min) ] | add) // 0 | round) as $human_s

| def sumu(f): ([ $amsgs[] | (.message.usage | f) // 0 ] | add) // 0;

  {
    session: {
      ts: $now,
      session_id: $sid,
      repo: $repo,
      branch: $branch,
      cwd: $cwd,
      started_at: ([ $E[].value.timestamp | select(. != null) ] | min),
      ended_at:   ([ $E[].value.timestamp | select(. != null) ] | max),
      version:    ([ $E[].value.version | select(. != null) ] | last),
      # seconds; see the time block above for what each one measures
      elapsed_seconds: $elapsed_s,
      active_seconds:  $active_s,
      human_seconds:   $human_s,
      agent_seconds:   ($active_s - $human_s),
      idle_seconds:    ($elapsed_s - $active_s),
      model:      ([ $E[].value | select(.type=="assistant")
                     | .message.model | select(. != null) ] | last),
      user_turns: ($humans | length),
      assistant_turns: ($amsgs | length),
      tool_calls: ($tools | length),
      tools: ($tools | group_by(.name)
              | map({key: .[0].name, value: length}) | from_entries),
      output_tokens: sumu(.output_tokens),
      input_tokens: sumu(.input_tokens),
      cache_creation_tokens: sumu(.cache_creation_input_tokens),
      cache_read_tokens: sumu(.cache_read_input_tokens),
      # Cache churn: creation/read as a percent. A cold start makes one
      # creation burst against zero reads, so a single-digit ratio is
      # normal; anything sustained above ~30% means the prompt cache kept
      # missing mid-session -- a stale-cache/reload proxy, not a token-cost
      # one. Null (not 0) when there were no reads at all, so a one-turn
      # session doesn't read as either healthy or churning.
      cache_churn_pct: (sumu(.cache_read_input_tokens) as $r
        | if $r > 0 then ((sumu(.cache_creation_input_tokens) / $r * 100) | round)
          else null end),
      context_peak: (([ $amsgs[] | .message.usage
                        | ((.input_tokens // 0) + (.cache_read_input_tokens // 0)
                           + (.cache_creation_input_tokens // 0)) ] | max) // 0),
      files_written: (([ $tools[] | select(.name | IN("Write","Edit","NotebookEdit"))
                         | .input.file_path // .input.notebook_path ]
                       + [ $tools[] | select(.name == "Bash")
                           | (.input.command // "")
                           | select(mutating_bash) | bash_targets[] ])
                      | unique | length),
      work_started: ($first_mut_raw != null),
      decisions: {
        total: ($decisions | length),
        scoping: ([ $decisions[] | select(.type == "scoping") ] | length),
        inline:  ([ $decisions[] | select(.type == "inline") ]  | length),
        gate:    ([ $decisions[] | select(.type == "gate") ]    | length)
      }
    },
    decisions: $decisions
  }
