#!/usr/bin/env python3
# Parity of lib/state.py with hooks/lib-state.sh. Run: python3 lib/state-parity.test.py
#
# What matters: the two languages give one answer. metrics-live.sh's live
# nag takes "archivable" from the shell functions and stop-continuity.py's
# Stop verdict from the Python ones; if they ever disagreed the 📦 notice
# and the checkpoint would answer the same question two ways
# (dotfiles#149). So each ported function runs in both over the same
# fixture repos and inputs, and the outputs must be equal, byte for byte.
# The locks are checked both ways round as well: each side must refuse a
# lock the other holds and reclaim the same stale ones, with one meta format.
#
# Cost per push: a few seconds, a step in CI's existing tool-tests job, so
# no new job and nothing drawn from the account's concurrent-job cap. What
# each function should answer is lib/state.test.py's to pin; this file only
# holds the two equal.
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent
LIB_STATE_SH = LIB.parent / "hooks" / "lib-state.sh"
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
CLOUD = ("/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch")
HOST = os.uname().nodename


def load():
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location("state_parity", LIB / "state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shell(script, *args, env=None):
    """Run script with lib-state.sh sourced; (status, stdout bytes)."""
    p = subprocess.run(["bash", "-c", f'. "{LIB_STATE_SH}"; {script}', "_", *args],
                       env=env or os.environ, capture_output=True)
    return p.returncode, p.stdout


def py(expr, env=None):
    """Evaluate expr in a fresh python with lib/state.py imported as state;
    (status, what it printed, as bytes). Fresh, so the pid in a lock's meta
    is a process of its own, as the shell's is."""
    code = ("import sys; sys.path.insert(0, %r); import state\n"
            "r = %s\n"
            "if isinstance(r, bool): sys.exit(0 if r else 1)\n"
            "sys.stdout.buffer.write(('' if r is None else r).encode('utf-8', 'surrogateescape'))\n"
            % (str(LIB), expr))
    p = subprocess.run([sys.executable, "-c", code], env=env or os.environ, capture_output=True)
    return p.returncode, p.stdout


def gitq(d, *args):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.T = Path(cls.tmp.name)
        cls.saved = dict(os.environ)
        os.environ.update(GITENV, HOME=str(cls.T / "home"))
        for k in ("CLAUDE_STATE_REPO", "HOOK_DIR", "STATE_LOCK_STALE_SECS"):
            os.environ.pop(k, None)
        (cls.T / "home").mkdir()
        cls.state = load()

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.saved)
        cls.tmp.cleanup()

    def same(self, sh_script, sh_args, py_value, label, strip_nl=False):
        _, out = shell(sh_script, *sh_args)
        want = out.rstrip(b"\n") if strip_nl else out
        got = py_value.encode("utf-8", "surrogateescape")
        self.assertEqual(got, want, f"{label}: python {got!r} vs shell {want!r}")

    # --- where state lives -----------------------------------------------------
    def test_lookup(self):
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        explicit = self.T / "explicit"
        homed = self.T / "home" / "code" / "claude_prompts_scratch"
        for label, make, env in (("none", None, {}),
                                 ("explicit", explicit, {"CLAUDE_STATE_REPO": str(explicit)}),
                                 ("explicit, not a repo", None, {"CLAUDE_STATE_REPO": str(self.T / "nope")}),
                                 ("on the home path", homed, {})):
            if make is not None:
                (make / ".git").mkdir(parents=True, exist_ok=True)
            e = dict(os.environ, **env)
            with self.subTest(label):
                for fn in ("state_repo", "state_dir"):
                    self.assertEqual(py(f"state.{fn}()", env=e)[1], shell(fn, env=e)[1], f"{fn}, {label}")
                self.assertEqual(py("state.state_is_repo()", env=e)[0], shell("state_is_repo", env=e)[0],
                                 f"state_is_repo, {label}")

    def test_shard_path(self):
        d = self.T / "shard"
        d.mkdir()
        (d / "flat.json").touch()
        for name, sid in (("3fa9-01.json", "3fa9-01"), ("2026-01-02-repo-3fa9.md", "3fa9-01"),
                          ("flat.json", "fl"), ("x.json", ""), ("y.json", "é1"), ("z.json", "a")):
            self.same('state_shard_path "$@"', (str(d), name, sid),
                      self.state.state_shard_path(str(d), name, sid), f"shard {name} {sid!r}")

    # --- unpushed_state, dirty_paths, archivable_reasons over one set of repos --
    def fixtures(self, pre=""):
        """(label, root, branch) for every git shape the verdict tells apart."""
        T = self.T / f"{pre}fx"
        T.mkdir()
        origin = T / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        w = T / "work"
        subprocess.run(["git", "init", "-q", "-b", "claude/work", str(w)], check=True)
        (w / "f").write_text("x\n")
        gitq(w, "add", "f")
        gitq(w, "commit", "-m", "base")
        gitq(w, "remote", "add", "origin", str(origin))
        gitq(w, "push", "-u", "origin", "claude/work")
        out = [("clean pushed", w, "claude/work")]

        def clone(name, *steps):
            c = T / name
            subprocess.run(["git", "clone", "-q", str(origin), str(c)], capture_output=True)
            for s in steps:
                s(c)
            return c

        def commit(c, name="g"):
            (c / name).write_text(name + "\n")
            gitq(c, "add", name)
            gitq(c, "commit", "-m", name)

        out.append(("one commit ahead of its upstream", clone("ahead", commit), "claude/work"))
        out.append(("never pushed", clone("never", lambda c: gitq(c, "checkout", "-b", "claude/new"), commit),
                    "claude/new"))
        out.append(("fresh branch, nothing ahead", clone("fresh", lambda c: gitq(c, "checkout", "-b", "claude/f")),
                    "claude/f"))
        out.append(("detached, a commit on no branch",
                    clone("detached", lambda c: gitq(c, "checkout", "--detach"), commit), "HEAD"))
        out.append(("detached on a remote branch", clone("detached0", lambda c: gitq(c, "checkout", "--detach")),
                    "HEAD"))
        out.append(("only on a wip/ salvage ref",
                    clone("wip", lambda c: gitq(c, "checkout", "-b", "claude/w"), commit,
                          lambda c: gitq(c, "push", "-q", "origin", "claude/w:refs/heads/wip/sid")), "claude/w"))
        out.append(("on a stack/ branch, @{u} elsewhere",
                    clone("stack", lambda c: gitq(c, "checkout", "-b", "claude/s"),
                          lambda c: gitq(c, "branch", "-u", "origin/claude/work"), commit,
                          lambda c: gitq(c, "push", "-q", "origin", "claude/s:refs/heads/stack/s")), "claude/s"))
        noorigin = T / "noorigin"
        subprocess.run(["git", "init", "-q", "-b", "claude/x", str(noorigin)], check=True)
        commit(noorigin)
        out.append(("no origin at all", noorigin, "claude/x"))
        out.append(("dirty, odd names",
                    clone("dirty", lambda c: (c / "f").write_text("changed\n"), lambda c: (c / "new file").touch(),
                          lambda c: (c / "café").touch(), lambda c: (c / "tab\tname").touch()), "claude/work"))
        out.append(("dirty and ahead", clone("both", commit, lambda c: (c / "dirt").touch()), "claude/work"))
        self.sr = clone("staterepo", lambda c: (c / "state" / "global").mkdir(parents=True),
                        lambda c: (c / "state" / "global" / "m.json").touch())
        out.append(("the state repo, state/ dirty", self.sr, "claude/work"))
        self.sr2 = clone("staterepo2", lambda c: (c / "state").mkdir(), lambda c: (c / "state" / "x").touch(),
                         lambda c: (c / "notes.txt").touch())
        out.append(("the state repo, other dirt", self.sr2, "claude/work"))
        out.append(("not a repo", self.T / "home", ""))
        return out

    def gate(self, hooks, home, items):
        """The fake hook dir: branch-home-gate.sh prints home, and the card
        for --card; the item store holds one item per (status, holder, age,
        brief) in items, or is absent for None."""
        g = hooks / "branch-home-gate.sh"
        g.write_text("#!/bin/sh\nif [ \"$1\" = --card ]; then echo 'pr https://github.com/o/r/pull/1'; "
                     f"else printf '%s\\n' '{home}'; fi\n")
        g.chmod(0o755)
        sl = self.T / "items"
        shutil.rmtree(sl, ignore_errors=True)
        os.environ["WORK_ITEM_DIR"] = str(sl)
        os.environ["WORK_ITEM_BIN"] = str(LIB.parent / "bin" / "work-item")
        if items is None:
            return
        sl.mkdir()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for n, (status, holder, stale, brief) in enumerate(items):
            t = "2026-09-01T00:00:00Z" if stale else now
            (sl / f"179083687{n}aaaaaaaa.md").write_text(
                f"# T\n\n## Brief\n{brief}\n\n## Log\n{t} 1d68120b status=open owner=agent repo=- parent=- model=- effort=-\n"
                f"{t} {holder} status={status}\n")

    def archivable_same(self, hooks, root, branch, sid, label):
        os.environ["HOOK_DIR"] = str(hooks)  # the shell function's input
        try:
            self.same('archivable_reasons "$@"', (str(root), branch, sid),
                      self.state.archivable_reasons(str(root), branch, sid, str(hooks)), label)
        finally:
            os.environ.pop("HOOK_DIR", None)

    def test_git_answers(self):
        hooks = self.T / "hooks"
        hooks.mkdir()
        self.gate(hooks, "home: pr https://github.com/o/r/pull/1", None)
        for label, root, branch in self.fixtures():
            sr = self.sr if "state/ dirty" in label else self.sr2
            for where, env in (("no state repo", None), ("state repo here", str(sr))):
                if env is None:
                    os.environ.pop("CLAUDE_STATE_REPO", None)
                else:
                    os.environ["CLAUDE_STATE_REPO"] = env
                with self.subTest(fixture=label, env=where):
                    self.same('unpushed_state "$@"', (str(root), branch),
                              self.state.unpushed_state(str(root), branch), f"unpushed_state, {label}")
                    self.same('dirty_paths "$@"', (str(root),), self.state.dirty_paths(str(root)),
                              f"dirty_paths, {label}")
                    self.archivable_same(hooks, root, branch, "abcd1234-0000", f"archivable_reasons, {label}")
        os.environ.pop("CLAUDE_STATE_REPO", None)

    def test_home_and_live_answers(self):
        # Over the one clean, pushed fixture, where reasons are empty until
        # the home and live checks: every home line and item-store reading.
        hooks = self.T / "hooks-live"
        hooks.mkdir()
        root = self.fixtures("live-")[0][1]
        card = "Fix it. https://github.com/o/r/pull/1"
        for home in ("home: pr https://github.com/o/r/pull/1", "unverified: gh failed (exit 1)",
                     "unverified:x", "no home", ""):
            for items in (None, [], [("claimed", "deadbeef", False, card)],
                          [("claimed", "deadbeef", True, card)], [("ready", "deadbeef", False, card)],
                          [("claimed", "deadbeef", False, "See o/r#1.")],
                          [("claimed", "deadbeef", False, "Other. https://github.com/o/r/pull/12")],
                          [("claimed", "deadbeef", False, "Other. o/r#12, o/r#100")],
                          [("claimed", "deadbeef", False, "Other. o/r#12, then o/r#1.")],
                          [("claimed", "abcd1234", False, card), ("claimed", "deadbeef", False, card)],
                          [("claimed", "abcd1234", False, card)]):
                self.gate(hooks, home, items)
                for sid in ("abcd1234-0000", "deadbeef-1111", ""):
                    with self.subTest(home=home, items=items, sid=sid):
                        self.archivable_same(hooks, root, "claude/work", sid, "archivable_reasons")
        os.environ.pop("WORK_ITEM_DIR", None)
        os.environ.pop("WORK_ITEM_BIN", None)

    # --- decision_rate -----------------------------------------------------------
    def test_decision_rate(self):
        for d, s in (("3", "4200"), ("1", "1800"), ("3", "0"), ("0", "60"), ("2", "59"), ("", ""),
                     ("5", "abc"), ("1.0", "3600"), ("7", "89.5"), ("100", "86400"), ("1", "59.9"),
                     ("12", "3599"), ("2.5", "900"), ("abc", "120"), (" 4", "7200 ")):
            self.same('decision_rate "$@"', (d, s), self.state.decision_rate(d, s), f"decision_rate {d!r} {s!r}",
                      strip_nl=True)

    # --- the locks, both ways round ------------------------------------------------
    def take(self, side, d):
        """One fresh process of side tries state_lock on d; (status, its meta
        with the pid masked, or "")."""
        if side == "sh":
            rc = shell('state_lock "$1"', str(d))[0]
        else:
            rc = py(f"state.state_lock({str(d)!r})")[0]
        try:
            meta = Path(d, "meta").read_text() if rc == 0 else ""
        except OSError:
            meta = "?"
        return rc, "\n".join("pid=*" if ln.startswith("pid=") else ln for ln in meta.split("\n"))

    def test_locks_agree(self):
        def held(pid, host=HOST):
            def f(d):
                d.mkdir()
                (d / "meta").write_text(f"pid={pid}\nhostname={host}\n")
            return f

        def bare(age):
            def f(d):
                d.mkdir()
                t = time.time() - age
                os.utime(d, (t, t))
            return f

        cases = {"free": lambda d: None,
                 "live pid, this host": held(os.getpid()),
                 "dead pid, this host": held(999999999),
                 "dead pid, another host": held(999999999, "elsewhere"),
                 "garbage pid": held("x1"),
                 "empty pid": held(""),
                 "no meta, old": bare(30),
                 "no meta, fresh": bare(0)}
        for n, (label, setup) in enumerate(cases.items()):
            got = {}
            for side in ("sh", "py"):
                d = self.T / f"lock{n}-{side}"
                setup(d)
                got[side] = self.take(side, d)
            with self.subTest(label):
                self.assertEqual(got["py"], got["sh"], f"{label}: python vs shell")
                if got["sh"][0] == 0:
                    self.assertEqual(got["sh"][1], f"pid=*\nhostname={HOST}\n", f"{label}: the meta format")
        nowhere = self.T / "nowhere" / "x.lock"
        self.assertEqual(self.take("py", nowhere), self.take("sh", nowhere), "a parent that does not exist")

    def test_each_side_refuses_the_others_live_lock(self):
        d = str(self.T / "shared.lock")
        # Python holds, bash asks.
        holder = subprocess.Popen([sys.executable, "-c",
                                   f"import sys, time; sys.path.insert(0, {str(LIB)!r}); import state\n"
                                   f"print(state.state_lock({d!r}), flush=True); time.sleep(30)"],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "True")
            self.assertEqual(Path(d, "meta").read_text(), f"pid={holder.pid}\nhostname={HOST}\n",
                             "python's meta is the shell's format")
            self.assertEqual(shell('state_lock "$1"', d)[0], 1, "bash refuses a lock python holds")
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        self.assertEqual(shell('state_lock "$1"', d)[0], 0, "and reclaims it once python is dead")
        # bash holds, Python asks.
        d2 = d + "2"
        holder = subprocess.Popen(["bash", "-c", f'. "{LIB_STATE_SH}"; state_lock "$1" && echo ok; exec sleep 30',
                                   "_", d2], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ok")
            self.assertEqual(py(f"state.state_lock({d2!r})")[0], 1, "python refuses a lock bash holds")
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        self.assertEqual(py(f"state.state_lock({d2!r})")[0], 0, "and reclaims it once bash is dead")

    def test_lock_wait_and_push_lock(self):
        d = self.T / "wait.lock"
        d.mkdir()
        (d / "meta").write_text(f"pid={os.getpid()}\nhostname={HOST}\n")
        self.assertEqual(py(f"state.state_lock_wait({str(d)!r}, 0)")[0], shell('state_lock_wait "$1" 0', str(d))[0],
                         "a held lock, no budget")
        free = self.T / "free.lock"
        self.assertEqual(py(f"state.state_lock_wait({str(free)!r}, 0)")[0], 0, "python: a free lock, no budget")
        self.assertEqual(shell('state_lock_wait "$1" 0', str(self.T / "free2.lock"))[0], 0,
                         "shell: a free lock, no budget")
        for tmp in (str(self.T), ""):
            env = dict(os.environ, TMPDIR=tmp)
            self.assertEqual(py("state.STATE_PUSH_LOCK", env=env)[1],
                             shell('printf %s "$STATE_PUSH_LOCK"', env=env)[1], f"STATE_PUSH_LOCK, TMPDIR={tmp!r}")


if __name__ == "__main__":
    unittest.main()
