#!/usr/bin/env python3
"""PreToolUse guard for mcp__Claude_Code_Remote__add_repo.

The continuity state repo must attach silently in every cold cloud session,
including auto mode -- that was the point of allowing add_repo at all. But a
bare allow rule can't see arguments, so it also let ANY repo attach with
push credentials, no prompt, on the say-so of whatever text steered the
session. This hook keeps the standing allow for exactly the one repo the
continuity hooks need and lets every other add_repo fall through to the
normal permission flow (a prompt when the user is present, a refusal in auto).

It only ever allows; a crash is traced and falls through to that same flow.
"""
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402


def main():
    ti = hookio.read().get("tool_input")
    if not isinstance(ti, dict):
        return
    if ti.get("owner") == "mark-brannan" and ti.get("repo") == "claude_prompts_scratch":
        hookio.emit(hookio.specific(
            "PreToolUse", permissionDecision="allow",
            permissionDecisionReason="continuity state repo -- standing allow"))


if __name__ == "__main__":
    lib_state.run_hook("guard-add-repo", "PreToolUse", main)
