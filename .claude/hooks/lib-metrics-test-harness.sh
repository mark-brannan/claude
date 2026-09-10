#!/usr/bin/env bash
# Shared harness for anything that drives metrics-live.sh with a synthetic
# transcript: metrics-live.test.sh (assertions) and metrics-live.examples.sh
# (rendered output, no assertions). Kept in one place so a transcript-shape
# change is fixed once, not in two scripts that quietly drift.
#
# Caller sets HOME/CLAUDE_STATE_REPO/SCRATCH before sourcing this.

# --- transcripts -------------------------------------------------------------
# One human turn plus one assistant turn carrying the context number. Appending
# another pair with a bigger number is how a session grows past a line.
turn() {  # turn <file> <context tokens>
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" \
    '{type:"queue-operation", operation:"enqueue", timestamp:$ts,
      sessionId:"t", content:"go on"}' >> "$1"
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" --argjson n "$2" \
    --arg u "req-$(wc -l < "$1" | tr -d ' ')" \
    '{type:"assistant", timestamp:$ts, requestId:$u,
      message:{model:"claude-opus-5", role:"assistant",
               content:[{type:"text", text:"ok"}],
               usage:{input_tokens:$n, output_tokens:10,
                      cache_read_input_tokens:0, cache_creation_input_tokens:0}}}' >> "$1"
}

payload() {  # payload <transcript> <session id> <cwd> [hook_event_name]
  jq -nc --arg tp "$1" --arg sid "$2" --arg cwd "$3" --arg h "${4:-}" \
    '{transcript_path:$tp, session_id:$sid, cwd:$cwd}
     + (if $h == "" then {} else {hook_event_name:$h} end)'
}

msg() { printf '%s' "$1" | jq -r '.systemMessage // ""' 2>/dev/null; }
ctx() { printf '%s' "$1" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }
