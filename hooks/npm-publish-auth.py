#!/usr/bin/env python3
"""PreToolUse hook: a Bash call running `npm publish` directly is denied and
pointed at `npm-publish-bg`, which does the same publish but pushes the
browser-2FA approval URL to the user out of band.

Why: the user's npm account uses browser passkey 2FA (see ~/.claude/rules/code.md,
"Publishing"). `npm publish` prints the approval URL mid-run, and that URL
is one of the strings the harness redacts from a Bash tool result before it
reaches Claude -- so a plain `npm publish` leaves Claude unable to read the
URL or relay it, and the publish sits waiting on an approval nobody was
told about. `npm-publish-bg` routes the URL to a notification and the
terminal instead. The rule for that lives in code.md; this hook is its
enforcement, because a rule that competes with "just run the command" loses
often enough to matter.

This hook only ever decides. It does not run the publish itself: a hook
that executed the command it was handed would bypass every other
PreToolUse guard in the chain (their deny would be advice about something
already done) and would run in the hook's working directory rather than
the tool's. Denying and letting the model re-issue one command through the
normal Bash path keeps both properties.

Convenience, not a gate: a missing languette plugin, a languette too old to
have `scan`, a command its scanner refuses, or a payload that won't parse,
exits 0 and the publish proceeds exactly as before.
"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402,F401  (puts lib/ on sys.path)
import hookio  # noqa: E402

REASON = (
    "Blocked by ~/.claude/hooks/npm-publish-auth.py: run `npm-publish-bg` instead of `npm publish` "
    "-- same arguments, same directory. The user's npm account uses browser passkey 2FA, and the "
    "approval URL npm prints is redacted from your tool result before you see it, so a plain publish "
    "stalls on an approval nobody was told about. npm-publish-bg runs the publish detached and pushes "
    "that URL to the user directly (browser, notification, terminal); you will never see it, by "
    "design, so don't ask for it or try to print it. It returns a pid and a logfile -- tail the log, "
    "and confirm with `npm view <pkg> dist-tags`. See ~/.claude/rules/code.md, 'Publishing'.")


def scanner():
    """Path of the languette plugin's scanner at the user-scope install Claude
    Code records in installed_plugins.json (a hook in settings.json gets no
    CLAUDE_PLUGIN_ROOT; that is set only for the plugin's own hooks). None
    when it cannot be found."""
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        with open(os.path.join(conf, "plugins", "installed_plugins.json")) as f:
            plugins = json.load(f)["plugins"]
        for key, installs in plugins.items():
            if not key.startswith("languette@"):
                continue
            for inst in installs:
                if inst.get("scope") == "user" and inst.get("installPath"):
                    path = os.path.join(inst["installPath"], "languette", "__main__.py")
                    return path if os.access(path, os.R_OK) else None
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass
    return None


def publishes(segments):
    """True when a segment -- top level, or nested inside a quoted `sh -c` or
    `eval` body -- has `publish` as npm's first non-flag argument. A quoted
    word (one holding whitespace) is never a flag or the subcommand.
    `--dry-run` passes: it never reaches the registry's auth, so there is no
    URL to lose, and /npm-first-publish runs it as a precondition. A global
    option that takes a separate value first (`npm --loglevel warn publish`)
    is not matched: resolving it needs a table of which npm flags consume the
    next word, and missing on the open side is the right way to miss."""
    for seg in segments:
        args = seg["words"][1:]
        first = next((w for w in args if w.get("quoted") or not w["text"].startswith("-")), None)
        if first is None or first.get("quoted") or first["text"] != "publish":
            continue
        if any(not w.get("quoted") and w["text"] in ("--dry-run", "--dry-run=true") for w in args):
            continue
        return True
    return False


def main():
    scan = scanner()
    if not scan:
        return 0
    ev = hookio.read()
    ti = ev.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else ""
    # Nearly every Bash call never says "publish", and the scanner costs a
    # Python start. A publish spelled by quote splicing (npm pu""blish) slips
    # past; this hook is a convenience, not a gate.
    if ev.get("tool_name") != "Bash" or not isinstance(cmd, str) or "publish" not in cmd:
        return 0
    # languette's scanner is the one the plugin's guards read commands with,
    # so a commit message or PR body that merely mentions "npm publish" does
    # not match, and `npm-publish-bg` is a different command word.
    try:
        p = subprocess.run([sys.executable, "-I", scan, "scan", "--command", "(^|/)npm$"],
                           input=cmd, capture_output=True, text=True)
        if p.returncode != 0:
            return 0
        matched = publishes(json.loads(p.stdout)["segments"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0
    if matched:
        hookio.emit(hookio.deny(REASON), ascii=False, compact=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
