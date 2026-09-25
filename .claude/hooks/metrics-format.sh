#!/usr/bin/env bash
# Display text for the metrics readouts, as plain printf. Sourced, never run.
#
# jq parses the transcript; it does not write what you read on screen
# (dotfiles#149). One function per field, so editing what you see is editing
# a printf here -- no jq program, no module include, no -L path. A field with
# nothing to say prints nothing rather than a zero or a "null".

# "⇢ 7 ⚙ 42" -- human turns, then tool calls. Never empty: the counts are
# the part of the turns line that always has a value.
fmt_turns() { printf '⇢ %s ⚙ %s' "${1:-0}" "${2:-0}"; }

# "⎇ 2c3~1↑unpushed  ← not safe to kill" -- commits, dirty files, unpushed.
# Empty on a clean tree, where "0c/0~/0↑" is the common case and says
# nothing. The kill warning rides on unpushed alone: that is the one state
# closing the chat loses work from.
fmt_work() {
  local s=""
  [ "${1:-0}" -gt 0 ] && s="$s${1}c"
  [ "${2:-0}" -gt 0 ] && s="$s${2}~"
  [ "${3:-0}" -gt 0 ] && s="$s${3}↑unpushed  ← not safe to kill"
  [ -n "$s" ] && printf '⎇ %s' "$s"
  return 0
}
