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
#   prose           -- the last assistant text before a human turn ends in
#                      a question mark, i.e. the turn stopped to ask
| ([ $tools[] | select(.name == "AskUserQuestion")
     | {i: .i, mechanism: "AskUserQuestion",
        n: ((.input.questions // []) | length),
        text: ((.input.questions // []) | map(.question) | join(" | "))} ]
   +
   [ $humans[] | select(. > 0) as $h
     | { i: $h,
         mechanism: "prose",
         n: 1,
         text: ([ $E[] | select(.key < $h and .value.type == "assistant")
                  | .value.message.content[]? | select(.type == "text")
                  | .text ] | last // "" | lastline) }
     | select(.text | test("\\?\\s*$")) ]
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
      context_peak: (([ $amsgs[] | .message.usage
                        | ((.input_tokens // 0) + (.cache_read_input_tokens // 0)
                           + (.cache_creation_input_tokens // 0)) ] | max) // 0),
      files_written: ([ $tools[] | select(.name | IN("Write","Edit","NotebookEdit"))
                        | .input.file_path // .input.notebook_path ]
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
