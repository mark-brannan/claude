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

# Persisted excerpts -- the friction excerpt and decisions[].question -- are
# written to metrics/ and pushed, so secret-shaped values come out of them
# first. The token-prefix list is the one `.config/yadm/hooks/pre_commit`
# uses, deliberately; the key-name list is wider, because that gate guards
# tracked prose in a public repo where a false positive blocks a commit, and
# this one guards a metrics excerpt where a false positive costs one
# unreadable line. clean_human has already dropped fenced blocks and pasted
# tool output -- where most pasted credentials live -- so this is here for the
# loose `export API_KEY=...` line that was never in a fence. The question is
# assistant text rather than pasted input, but the assistant routinely quotes
# a config line back when asking which value to use, so it runs through the
# same filter.
| def redact:
    gsub("(?i)(?<k>(api|access|auth|oauth|bearer|client|secret|private|refresh|session)[_-]?(key|token|secret)|_authtoken|passwo?r?d|passphrase|credential)(?<s>\\s*[:=]\\s*)[^\\s'\"]{6,}";
         "\(.k)\(.s)[redacted]")
    | gsub("(?i)\\b(?<b>bearer)\\s+[A-Za-z0-9._~+/=-]{16,}"; "\(.b) [redacted]")
    | gsub("npm_[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|BEGIN [A-Z ]*PRIVATE KEY";
           "[redacted]");

# --- decisions -----------------------------------------------------------
# Two mechanisms, both mechanically detectable:
#   AskUserQuestion -- an explicit, structured hand-off
#   prose           -- the last assistant text before a human turn is an ask
#                      (see is_ask): a trailing question, an enumerated
#                      escalation, or either of those under a fenced block
([ $tools[] | select(.name == "AskUserQuestion")
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
        question: (.text | redact | .[0:300])} ]) as $decisions

# --- friction --------------------------------------------------------------
# A friction event is a human turn that contradicts, corrects, overrides or
# rebukes the assistant turn before it. Anchored at the human enqueue index,
# same as $humans, so friction and decisions share one timeline. Full spec:
# claude_prompts_scratch/state/global/log/2026-08-21-friction-metric-spec.md

# Text of every human enqueue, keyed by turn index -- same source as $humans.
| ([ $E[] | select(.value.type == "queue-operation" and .value.operation == "enqueue"
                   and (.value.content // "") != "")
    | {i: .key, text: .value.content} ]) as $human_texts

# Assistant text, one entry per assistant record that has any, keyed by index.
| ([ $E[] | select(.value.type == "assistant") | .key as $i
    | ([ .value.message.content[]? | select(.type == "text") | .text ] | join("\n")) as $t
    | select($t != "")
    | {i: $i, text: $t} ]) as $atext

# Tool-result text, keyed by index. The index is load-bearing for the caps
# check below, which may only look at output that already existed when the
# human turn was written.
| ([ $E[] | select(.value.type == "user") | .key as $i
    | .value.message.content[]? | select(.type == "tool_result")
    | {i: $i,
       t: (.content | if type == "array" then ([ .[] | .text? // empty ] | join("\n"))
                      elif type == "string" then .
                      else "" end)} ]) as $tool_texts

# The same text flattened to a set of lines, so clean_human can strip
# pasted hook/command output out of human turns before any regex runs, and a
# quoted command result cannot trip the S3 quote-back check. A set, not an
# array: clean_human tests every line of every human turn against it, and
# `index` on an array is a linear scan.
| ([ $tool_texts[].t ]
   | map(split("\n")[]) | map(gsub("^\\s+|\\s+$"; ""))
   | map(select(. != ""))
   | reduce .[] as $l ({}; .[$l] = true)) as $tool_lines

# Whole-transcript interrupt/decline markers, for S7. Zero-cost: neither
# calibration transcript hits it, but it is free to compute.
| ([ $E[] | .key as $i | .value
    | (( .message.content[]? | select(.type == "tool_result")
         | (.content | if type == "array" then ([ .[] | .text? // empty ] | join(" "))
                        elif type == "string" then . else "" end) ) // "") as $trtext
    | select(($trtext | test("doesn'?t want to proceed|The user declined"))
             or ((tostring) | test("\\[Request interrupted by user")))
    | $i ]) as $veto_at

# --- blocked: the harness refused a tool call --------------------------------
# Not human friction -- nobody corrected anything, the permission layer said
# no. Tracked separately because it costs Mark the same currency: a retry, a
# workaround, or a decision about his own settings. Previously invisible, so
# "the classifier keeps blocking things" was an impression with no number.
#
# `toolDenialKind` is set by the harness on the denial record itself, so this
# reads a field rather than matching prose -- a denial message is written by
# whichever hook refused and cannot be pattern-matched in general. Observed
# values: automode-blocked, automode-unavailable, permission-rule,
# user-rejected. An unrecognised value passes through under its own name
# rather than being dropped, so a new kind shows up as itself instead of
# silently vanishing.
| ([ $E[] | .value | select(.type == "assistant")
    | .message.content[]? | select(.type == "tool_use")
    | {key: (.id // ""), value: {name: .name, input: .input}} ] | from_entries) as $tool_by_id

# Correlated by tool_use_id, not by position: one assistant turn can issue
# several tool_use blocks that all share its transcript index, so picking the
# nearest preceding one mislabels which call in a parallel batch was refused.
| ([ $E[] | .key as $i | .value | select(.toolDenialKind != null)
    | .toolDenialKind as $k
    | ([ .message.content[]? | select(.type == "tool_result") | .tool_use_id ] | first) as $tid
    | ($tool_by_id[$tid // ""] // {}) as $tu
    | {i: $i,
       kind: (if ($k | startswith("automode")) then "classifier"
              elif $k == "permission-rule" then "rule"
              elif $k == "user-rejected" then "user"
              else $k end),
       raw: $k,
       tool: ($tu.name // ""),
       target: ((($tu.input.command // $tu.input.file_path // "") | tostring
                  # redact before truncating: a 160-char cut can land mid-token
                  # and leave a partial secret the pattern no longer matches.
                  | redact) | .[0:160])} ]) as $blocked

| def strip_fences: gsub("```[^`]*```"; "");
def clean_human:
    strip_fences | split("\n")
    | map(gsub("^\\s+|\\s+$"; ""))
    | map(select(test("^Stop says:") | not))
    | map(select(test("^>") | not))
    | map(select(. as $l | ($tool_lines | has($l)) | not))
    | join("\n");

def s1_first_re: "(?i)^(no|nope|wrong|not)\\b[?.,!:]?";
def s1_conduct_re: "(?i)stop (hedging|arguing|speculating)|don'?t (want to hear|hedge)|you'?re not making|quantify";
def s1_any_re: "(?i)you'?re not|that'?s (wrong|not)|I (said|told you)|not what I|disagree|stop (hedging|arguing|speculating)|don'?t (want to hear|hedge)|quantify|have to remind you|already happened|you keep (saying|doing)|not the first time";
# A paragraph of an assistant turn that opens by owning a mistake. Scored on
# its own, not through a human turn, so a woopsy Claude caught itself still
# gets logged. Tested per line (jq's ^ only anchors the string) with at most
# 30 chars of lead-in, so a mention deep in prose does not count.
def s9_self_re: "(?i)^[^\\n]{0,30}?((mistake|correction|error) on my side|my mistake|I (misread|got that wrong))";
def s5_undo_re: "(?i)^(no[,.!]?\\s*)?(take (it|that|this)? ?out|remove|revert|undo|put (it )?back|don'?t|stop)\\b";
def s4_words_re: "(?i)fuck\\w*|dumb|stupid|idiot|thick (silicon )?skull";
def s1_first: test(s1_first_re);
def s1_conduct: test(s1_conduct_re);
def s1_any: test(s1_any_re);
def s2_retract: test("(?i)^(fair|you'?re right|that (claim|was) (was )?wrong|bad call|my mistake|I was wrong|I (hadn'?t|misread|assumed)|dropping it|scratch that)");
def s5_undo: test(s5_undo_re);
def s8_pushback: test("(?i)I('d| would) still|I disagree|doesn'?t change the answer|recommend(ation)?:? (ignore|reject|don'?t)|that case stands");
def s4_words: test(s4_words_re);
# The exact substrings a detector fired on, so a friction record says what
# tripped it rather than only that something did.
def phrases($re): [ match($re; "g") | .string | select(. != "") ];

# Words already said by Claude or a tool, lowercased, so a shouted identifier
# Claude itself printed (SHOW, EVENT_ARG, PR, WSL) never counts as heat.
#
# Prior-only, not whole-transcript. Scanning the whole transcript let a word
# Claude first uttered *after* the shout retroactively suppress it: append one
# assistant turn saying "right, absolutely, not what asked for" and the
# preceding ABSOLUTELY NOT WHAT I ASKED FOR downgraded from rebuke to
# override. Words are attributed to the record they appeared in, and each
# human turn is scored against the set as it stood at that point.
([ ($atext[] | {i: .i, t: .text}), ($tool_texts[] | {i: .i, t: .t}) ]
 | map({i: .i, w: (.t | [ scan("[A-Za-z]{3,}") ] | map(ascii_downcase))})) as $src_words

# One snapshot of that set per human turn, from a single ordered pass. jq
# values are persistent, so parking the accumulator in .snap stores a
# reference, not a copy of every word seen so far -- the naive
# "filter $src_words by index inside the per-turn map" is quadratic in the
# transcript, and this runs in a blocking Stop hook.
| (reduce (([ $humans[] | {i: ., h: true} ] + [ $src_words[] | {i: .i, h: false, w: .w} ])
           | sort_by([.i, (if .h then 0 else 1 end)]))[] as $r
     ({seen: {}, snap: {}};
      if $r.h then .snap[$r.i | tostring] = .seen
      else .seen = (reduce $r.w[] as $w (.seen; .[$w] = true)) end)
   | .snap) as $seen_before

| def s4_caps($seen):
    ([ scan("[A-Z]{3,}") ]
     | map(select(test("[0-9_]") | not))
     | map(. as $w | select(($seen | has($w | ascii_downcase)) | not))
     | length) >= 3;

([ $tools[] | select(is_mutating) | .i ]) as $mut_is
| def mutated_between($lo; $hi): [ $mut_is[] | select(. > $lo and . < $hi) ] | length > 0;
def prev_ask($h): (last($atext[] | select(.i < $h)) // {text: null}).text | ask_text;

# One record per human turn, everything the tags need already resolved.
($humans | to_entries | map(
    .key as $pos | .value as $h
    | (if $pos == 0 then -1 else $humans[$pos - 1] end) as $prev
    | (($human_texts[] | select(.i == $h) | .text) // "") as $raw
    | ($raw | clean_human) as $clean
    | (prev_ask($h) != null and ($clean | length) < 40) as $is_answer
    | ($clean | s1_conduct) as $conduct_hit
    # A short reply to a question is "no" answering, not friction -- unless
    # it hit the conduct subset (stop hedging/quantify/...), which is never
    # a bare answer regardless of length.
    | ($conduct_hit or (($is_answer | not) and ($clean | (s1_first or s1_any)))) as $lexicon
    | ($lexicon and $conduct_hit) as $lexicon_conduct
    | ([ $clean | scan("\"([^\"]{20,})\"") ] | map(.[0])) as $quotes
    # $before_text is every prior assistant turn concatenated, so building it
    # for each human turn is quadratic in the transcript -- and it is only
    # ever read when the turn actually contains a quote, which is rare. jq's
    # `and` short-circuits, so keeping it on the right-hand side means most
    # turns never pay for it. This runs in a blocking Stop hook: on a 600-turn
    # synthetic transcript the friction pass cost 7.7s before this and the
    # $tool_lines set below, 3.4s after, against a 1.1s pre-friction baseline.
    | (($quotes | length) > 0
       and (([ $atext[] | select(.i < $h) | .text ] | join("\n")) as $before_text
            | $quotes | any(. as $q | $before_text | contains($q)))) as $quote
    | mutated_between($prev; $h) as $mutated_before
    | ((($clean | split("\n") | first) // "") | s5_undo) as $undo_line
    | ($undo_line and $mutated_before) as $undo
    | (($seen_before[$h | tostring]) // {}) as $seen
    | ($clean as $c | ($c | s4_caps($seen)) or ($c | s4_words)) as $heat
    | first($atext[] | select(.i > $h)) as $next
    | ((($next.text // "")[0:200]) | s2_retract) as $retracted
    | (($veto_at | map(select(. > $prev and . <= $h)) | length) > 0) as $veto
    | ([ (if $lexicon then "lexicon" else empty end),
         (if $quote   then "quote"   else empty end),
         (if $undo    then "undo"    else empty end),
         (if $heat    then "heat"    else empty end),
         (if $veto    then "veto"    else empty end) ]) as $tags
    # The cleaned text, not $raw: the excerpt is persisted and pushed, and
    # $raw still carries whatever the human pasted in -- fenced blocks, hook
    # output, a captured command result. clean_human already stripped those
    # for the detectors; keeping the excerpt on the same text means nothing
    # reaches disk that the metric did not actually read.
    | ([ (if $lexicon then ($clean | phrases(s1_first_re), phrases(s1_conduct_re), phrases(s1_any_re)) else empty end),
         (if $undo then ((($clean | split("\n") | first) // "") | phrases(s5_undo_re)) else empty end),
         (if $heat then ($clean | phrases(s4_words_re)),
                        ($clean | [ scan("[A-Z]{3,}") ] | map(select(test("[0-9_]") | not))
                                 | map(. as $w | select(($seen | has($w | ascii_downcase)) | not)))
                   else empty end) ]
       | add // [] | unique) as $hits
    | ((last($atext[] | select(.i < $h)) // {text: ""}).text | redact
       | .[0:120] | . as $head
       | ([ match("^[\\s\\S]{40,}?[.!?](?=\\s|$)") ] | if length > 0 then .[0].string else $head end)) as $prior
    | {i: $h, pos: $pos, text: ($clean | redact), tags: $tags, hits: $hits, prior: $prior,
       lexicon_conduct: $lexicon_conduct, retracted: $retracted,
       has_event: (($tags | length) > 0 or $retracted)}
  )) as $human_tagged

# Sequential pass: `repeat` and `type` both depend on the previous *event*,
# not the previous human turn, so this can't be a per-record map.
| (reduce ($human_tagged[] | select(.has_event)) as $ht
    ({events: [], last_h: -1, last_pos: -1};
     ( .last_h != -1
       and ((($ht.pos) - .last_pos) <= 2)
       and (mutated_between(.last_h; $ht.i) | not) ) as $repeat
     | ( if ($ht.tags | any(. == "heat" or . == "quote"))
           or $ht.lexicon_conduct
           # A repeat that was not retracted is forced to rebuke. Kept
           # deliberately: on the contentious fixture repeat is 7 of 11 and
           # rebuke is also 7, which reads like the classifier is measuring
           # consecutiveness rather than severity -- it is not. Dropping this
           # clause moves exactly one event (rebuke 7 -> 6, override 2 -> 3),
           # measured; the other six rebukes come from heat, quote or a
           # conduct lexicon hit on their own.
           or ($repeat and ($ht.retracted | not))
         then "rebuke"
         elif $ht.retracted then "correction"
         else "override"
         end ) as $type
     | .events += [ $ht + {repeat: $repeat, type: $type} ]
     | .last_h = $ht.i | .last_pos = $ht.pos
    )
  ).events as $friction_events

# --- pushback: assistant re-argues in the turn right after a tagged human
# turn (lexicon/undo/heat -- not a bare quote or silent retraction).
| ([ $atext[] | select(.text | s8_pushback) | .i as $ai
    | last($humans[] | select(. < $ai)) as $ph
    | select($ph != null)
    | ($friction_events[] | select(.i == $ph)) as $ev
    | select($ev.tags | any(. == "lexicon" or . == "undo" or . == "heat")) ]
  | length) as $pushback

| ([ $friction_events | to_entries[]
     | .key as $seq | .value
     | {ts: $now, session_id: $sid, repo: $repo, branch: $branch,
        seq: ($seq + 1),
        turn_index: .i,
        type: .type,
        tags: .tags,
        retracted: .retracted,
        repeat: .repeat,
        slug: ($ARGS.named.slug // ""),
        hits: .hits,
        excerpt: (.text | .[0:300]),
        prior: .prior} ]) as $friction_human
| ([ $atext[] | (first(.text | split("\n")[] | select(test(s9_self_re))) // empty) as $line
     | {ts: $now, session_id: $sid, repo: $repo, branch: $branch,
        seq: 0, turn_index: .i, type: "self_report", tags: ["self_report"],
        retracted: false, repeat: false,
        slug: ($ARGS.named.slug // ""),
        hits: [ $line | match(s9_self_re) | .captures[0].string ],
        excerpt: ($line | redact | .[0:300]),
        prior: ""} ]) as $self_reports
| (($friction_human + $self_reports) | sort_by(.turn_index)
   | to_entries | map(.value + {seq: (.key + 1)})) as $friction

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
      },
      blocked: {
        total:      ($blocked | length),
        classifier: ([ $blocked[] | select(.kind == "classifier") ] | length),
        rule:       ([ $blocked[] | select(.kind == "rule") ]       | length),
        user:       ([ $blocked[] | select(.kind == "user") ]       | length)
      },
      friction: {
        total:      ($friction_human | length),
        self_report: ($self_reports | length),
        correction: ([ $friction[] | select(.type == "correction") ] | length),
        override:   ([ $friction[] | select(.type == "override") ]   | length),
        rebuke:     ([ $friction[] | select(.type == "rebuke") ]     | length),
        repeat:     ([ $friction[] | select(.repeat) ]                | length),
        pushback:   $pushback
      }
    },
    decisions: $decisions,
    friction: $friction,
    blocked: $blocked
  }
