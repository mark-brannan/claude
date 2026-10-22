#!/usr/bin/env python3
# Tests for claim-stamp.py. Run: python3 hooks/claim-stamp.test.py
#
# `gh` is stubbed throughout, backed by a comment store on disk, so the tests
# exercise the real post/patch/delete sequencing without ever reaching GitHub.
# The stub hands gh's --jq program to the real jq, as gh would run it.
# What matters: a claim writes exactly one stamp and patches it rather than
# posting a second; a second session is warned by name and age; a stale stamp
# is collected; release removes the label only when no stamp is left; refresh
# is free -- no network at all -- when this session claimed nothing; and the
# stamp, the record and the ledger keep the shape bin/ readers parse.
#
# CS_CMD (a command line, split on spaces) runs another implementation of the
# same command line under these cases; it defaults to this directory's .py.
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CS = os.environ.get("CS_CMD", "").split() or [sys.executable, str(HERE / "claim-stamp.py")]
URL7 = "https://github.com/o/r/pull/7"
CARD = "https://github.com/o/r/issues/12"

STUB = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
S = os.environ["CLAIM_STORE"]
a = sys.argv[1:]
with open(S + "/calls", "a") as fh:
    fh.write(" ".join(a) + "\n")
if os.environ.get("GH_FAIL") == "1":
    sys.exit(1)
if os.environ.get("GH_FAIL_API") == "1" and a[:1] == ["api"]:
    sys.exit(1)
if a[:1] == ["pr"]:
    print(os.environ.get("GH_PRS" if "--head" in a else "GH_PRS_ALL") or "[]")
    sys.exit(0)
if a[:1] == ["issue"]:
    print(os.environ.get("GH_ISSUES") or "[]")
    sys.exit(0)
if a[:1] != ["api"]:
    sys.exit(1)
a = a[1:]
method, path, jq = "GET", "", None
while a:
    if a[0] == "-X": method, a = a[1], a[2:]
    elif a[0] == "--jq": jq, a = a[1], a[2:]
    elif a[0] == "--input": a = a[2:]
    elif a[0] == "--paginate": a = a[1:]
    elif a[0] == "-f":
        with open(S + "/labels", "a") as fh:
            fh.write(a[1] + "\n")
        a = a[2:]
    else: path, a = a[0], a[1:]
C = S + "/comments"
def emit(obj):
    text = json.dumps(obj)
    if jq:
        sys.stdout.write(subprocess.run(["jq", "-r", jq], input=text, capture_output=True, text=True).stdout)
    else:
        sys.stdout.write(text)
def load(n):
    return json.load(open(f"{C}/{n}"))
if method == "GET" and path.endswith("/comments"):
    emit([load(n) for n in sorted(os.listdir(C))])
elif method == "POST" and path.endswith("/comments"):
    try: n = int(open(S + "/next").read()) + 1
    except OSError: n = 101
    open(S + "/next", "w").write(str(n))
    json.dump({"id": n, "body": json.load(sys.stdin)["body"]}, open(f"{C}/{n}.json", "w"))
    emit(load(f"{n}.json"))
elif method == "PATCH" and "/issues/comments/" in path:
    n = path.rsplit("/", 1)[1]
    if not os.path.isfile(f"{C}/{n}.json"): sys.exit(1)
    json.dump({"id": int(n), "body": json.load(sys.stdin)["body"]}, open(f"{C}/{n}.json", "w"))
    emit(load(f"{n}.json"))
elif method == "DELETE" and "/issues/comments/" in path:
    try: os.remove(f"{C}/{path.rsplit('/', 1)[1]}.json")
    except OSError: pass
elif method == "DELETE" and "/labels/" in path:
    with open(S + "/labels", "a") as fh:
        fh.write("removed " + path.rsplit("/", 1)[1] + "\n")
else:
    sys.exit(1)
'''


def gitq(d, *args):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], capture_output=True, check=False)


class ClaimStampTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "store"
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(STUB)
        (bindir / "gh").chmod(0o755)
        home, tmpd = self.tmp / "home", self.tmp / "tmp"
        home.mkdir()
        tmpd.mkdir()
        self.tmpd = tmpd
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "CLAUDE_CLAIM_STAMP")}
        env.update(HOME=str(home), TMPDIR=str(tmpd), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                   CLAUDE_STATE_REPO=str(self.tmp / "nostate"), CLAIM_STORE=str(self.store),
                   PATH=f"{bindir}:{os.environ.get('PATH', '')}", GH_PRS=json.dumps([{"url": URL7}]))
        self.env = env
        self.ledger = home / ".claude/state/global/claims"
        self.work = self.tmp / "work"
        self.reset_store()

    # -- fixtures ------------------------------------------------------------
    def repo(self, branch):
        origin = self.tmp / "origin.git"
        shutil.rmtree(origin, True)
        shutil.rmtree(self.work, True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True)
        gitq(self.work, "remote", "add", "origin", str(origin))
        (self.work / "f").write_text("one\n")
        gitq(self.work, "add", "--", "f")
        gitq(self.work, "commit", "-m", "one")
        gitq(self.work, "push", "-u", "origin", "main")
        if branch:
            gitq(self.work, "checkout", "-b", branch)
            (self.work / "g").write_text("two\n")
            gitq(self.work, "add", "--", "g")
            gitq(self.work, "commit", "-m", "two")
            gitq(self.work, "push", "-u", "origin", branch)

    def reset_store(self):
        shutil.rmtree(self.store, True)
        (self.store / "comments").mkdir(parents=True)
        (self.store / "calls").write_text("")
        (self.store / "labels").write_text("")

    def plant(self, n, sid, epoch):
        (self.store / "comments" / f"{n}.json").write_text(json.dumps(
            {"id": n, "body": f"<!-- claim-stamp sid={sid} epoch={epoch} machine=host-000000 -->"}))

    def cs(self, *args, stdin=None, **env):
        p = subprocess.run([*CS, *args], input=stdin, capture_output=True, text=True,
                           env={**self.env, **env})
        return p.returncode, p.stdout, p.stderr

    def out(self, *args, **env):
        return self.cs(*args, **env)[1].rstrip("\n")

    def bodies(self):
        return "\n".join(json.loads(f.read_text())["body"] for f in sorted((self.store / "comments").glob("*.json")))

    def ncomments(self):
        return len(list((self.store / "comments").glob("*.json")))

    def ncalls(self):
        return len([ln for ln in (self.store / "calls").read_text().split("\n") if ln])

    def labels(self):
        return (self.store / "labels").read_text()

    def rec(self, sid):
        return self.tmpd / ("claude-claim-stamp." + re.sub(r"[^A-Za-z0-9_-]", "_", sid))

    def age_ledger(self, s8):
        f = next(self.ledger.glob(f"*-{s8}.tsv"))
        p = f.read_text().rstrip("\n").split("\t")
        p[2] = "1"
        f.write_text("\t".join(p) + "\n")

    # -- branch claims -------------------------------------------------------
    def test_claim_release_and_warning(self):
        self.repo("claude/claimed")
        out = self.out("claim", "-C", str(self.work), "aaaaaaaa11112222")
        self.assertEqual(self.ncomments(), 1, "one stamp is posted")
        b = self.bodies()
        host = socket.gethostname()
        machine = "host-" + __import__("hashlib").sha256(host.encode()).hexdigest()[:6]
        # The stamp's exact shape: the marker line bin/grind-check and prt parse.
        self.assertRegex(b, re.compile(
            r"\A<!-- claim-stamp sid=aaaaaaaa epoch=[0-9]{10} machine=" + machine + r" -->\n"
            r"\*\*Claimed:\*\* `aaaaaaaa` · `claude/claimed` · `" + machine +
            r"` · [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\n\n"
            r"A session holds this work\. The Stop hook refreshes the timestamp; `/wrapup`\n"
            r"and the archive verdict delete this comment\. Older than 2h and\n"
            r"the claim is stale -- the session that wrote it died without releasing it\.\Z"))
        self.assertNotIn(host, b, "the machine is a hash, not a name")
        self.assertEqual(out, "", "an uncontested claim says nothing")
        self.assertIn("labels[]=claimed", self.labels())
        self.assertRegex(self.rec("aaaaaaaa11112222").read_text(), r"\Ao/r#7\t[0-9]+\t[0-9]{10}\n\Z",
                         "the record's shape")

        self.cs("claim", "-C", str(self.work), "aaaaaaaa11112222")
        self.assertEqual(self.ncomments(), 1, "the same session patches its stamp")

        out = self.out("claim", "-C", str(self.work), "bbbbbbbb33334444")
        self.assertRegex(out, r"^session `aaaaaaaa` on `host-[0-9a-f]{6}` claimed `claude/claimed` 0 minute\(s\) ago$")
        self.assertEqual(self.ncomments(), 2, "and it stamps too -- both are real")

        (self.store / "labels").write_text("")
        self.cs("release", "-C", str(self.work), "bbbbbbbb33334444")
        self.assertEqual(self.ncomments(), 1, "release deletes its own stamp")
        self.assertIn("sid=aaaaaaaa", self.bodies())
        self.assertEqual(self.labels(), "", "the label stays while a stamp does")
        self.assertFalse(self.rec("bbbbbbbb33334444").exists())

        self.cs("release", "-C", str(self.work), "aaaaaaaa11112222")
        self.assertEqual(self.ncomments(), 0, "the last release clears the card")
        self.assertIn("removed claimed", self.labels())

    def test_stale_and_fresh_holders(self):
        self.repo("claude/claimed")
        self.plant(1, "deadbeef", 1)
        out = self.out("claim", "-C", str(self.work), "ccccccccc5556666")
        self.assertEqual(self.ncomments(), 1, "the stale stamp is deleted")
        self.assertIn("sid=cccccccc", self.bodies())
        self.assertEqual(out, "", "a stale holder is not warned about")

        self.reset_store()
        self.plant(1, "deadbeef", int(time.time()) - 60)
        out = self.out("claim", "-C", str(self.work), "dddddddd77778888")
        self.assertIn("session `deadbeef`", out)
        self.assertIn("1 minute(s) ago", out)
        self.assertEqual(self.ncomments(), 2, "a fresh stamp is left alone")

        self.reset_store()
        self.plant(1, "deadbeef", int(time.time()) - 60)
        self.cs("claim", "-C", str(self.work), "eeeeeeee99990000", CLAIM_STALE_SECS="30")
        self.assertEqual(self.ncomments(), 1, "a lower threshold collects it")

    def test_refresh(self):
        self.repo("claude/claimed")
        self.cs("claim", "-C", str(self.work), "ffffffffaaaabbbb")
        before = self.bodies()
        (self.store / "calls").write_text("")
        self.cs("refresh", "-C", str(self.work), "ffffffffaaaabbbb")
        self.assertEqual(self.ncalls(), 0, "refresh inside the debounce is free")
        self.assertEqual(self.bodies(), before)
        self.cs("refresh", "-C", str(self.work), "ffffffffaaaabbbb", CLAIM_REFRESH_SECS="0")
        self.assertGreater(self.ncalls(), 0, "past the debounce it patches")
        self.assertEqual(self.ncomments(), 1)
        (self.store / "calls").write_text("")
        self.cs("refresh", "-C", str(self.work), "99999999ccccdddd")
        self.assertEqual(self.ncalls(), 0, "refresh without a record is free")

    def test_scan_release(self):
        self.repo("claude/claimed")
        self.plant(1, "abcd0000", int(time.time()))
        (self.store / "calls").write_text("")
        self.cs("release", "-C", str(self.work), "abcd000012345678")
        self.assertEqual(self.ncalls(), 0, "release without a record is free")
        self.assertEqual(self.ncomments(), 1)
        self.cs("release", "-C", str(self.work), "--scan", "abcd000012345678")
        self.assertEqual(self.ncomments(), 0, "--scan finds it by its marker")

    def test_stop_release_is_provisional(self):
        self.repo("claude/resumed")
        sid = "cafe0000aaaabbbb"
        self.cs("claim", "-C", str(self.work), sid)
        self.cs("release", "-C", str(self.work), sid)
        self.assertEqual(self.ncomments(), 0)
        self.assertTrue(Path(f"{self.rec(sid)}.released").exists(), "a tombstone")
        self.cs("refresh", "-C", str(self.work), sid)
        self.assertEqual(self.ncomments(), 1, "refresh after it re-claims")
        self.assertTrue(self.rec(sid).exists())
        self.assertFalse(Path(f"{self.rec(sid)}.released").exists())
        self.cs("release", "-C", str(self.work), "--scan", sid)
        self.assertEqual(self.ncomments(), 0)
        self.assertFalse(Path(f"{self.rec(sid)}.released").exists(), "a --scan release is final")
        (self.store / "calls").write_text("")
        self.cs("refresh", "-C", str(self.work), sid)
        self.assertEqual(self.ncalls(), 0)

    def test_nothing_to_claim(self):
        self.repo("")
        self.cs("claim", "-C", str(self.work), "11111111eeeeffff")
        self.assertEqual(self.ncomments(), 0, "the default branch is a no-op")
        self.assertEqual(self.ncalls(), 0, "and costs no network")
        self.repo("claude/uncarded")
        self.cs("claim", "-C", str(self.work), "22222222eeeeffff", GH_PRS="[]", GH_PRS_ALL="[]", GH_ISSUES="[]")
        self.assertEqual(self.ncomments(), 0, "a branch with no card is a no-op")

    def test_never_under_ci_and_never_fails(self):
        self.repo("claude/ci")
        self.cs("claim", "-C", str(self.work), "33333333eeeeffff", GITHUB_ACTIONS="true")
        self.cs("claim", "-C", str(self.work), "33333333eeeeffff", CI="1")
        self.cs("claim", "-C", str(self.work), "33333333eeeeffff", CLAUDE_CLAIM_STAMP="off")
        self.assertEqual(self.ncomments(), 0)
        self.assertEqual(self.cs("claim", "-C", str(self.work), "44444444eeeeffff", GH_FAIL="1")[0], 0)
        nogh = self.tmp / "nogh"
        nogh.mkdir()
        for b in ("sh", "git", "sed", "tr", "cat", "awk", "cut", "timeout", "dirname", "uname"):
            p = shutil.which(b)
            if p:
                (nogh / b).symlink_to(p)
        self.assertEqual(self.cs("claim", "-C", str(self.work), "55555555eeeeffff", PATH=str(nogh))[0], 0,
                         "no gh at all still exits 0")

    def test_read(self):
        self.repo("claude/readable")
        self.cs("claim", "-C", str(self.work), "66666666eeeeffff")
        self.plant(9, "deadbeef", 1)
        out = self.out("read", "-C", str(self.work))
        self.assertRegex(out, r"(?m)^live\t66666666\thost-[0-9a-f]{6}\t0m\t" + re.escape(URL7) + "$")
        self.assertRegex(out, r"(?m)^stale\tdeadbeef\thost-000000\t[0-9]+m\t" + re.escape(URL7) + "$")
        rc, out, _ = self.cs("read", "-C", str(self.work), GH_FAIL_API="1")
        self.assertEqual(out, f"unverified: could not read the stamps on {URL7}\n")
        self.assertEqual(rc, 0)
        self.assertTrue(self.out("read", "-C", str(self.work), GH_FAIL="1").startswith("unverified"))
        out = self.out("read", URL7)
        self.assertRegex(out, r"(?m)^live\t66666666.*pull/7$", "read <url> needs no checkout")
        self.assertRegex(out, r"(?m)^stale\tdeadbeef")
        self.assertEqual(self.out("read", "https://example.com/x"), "unverified: bad card url https://example.com/x")
        self.reset_store()
        self.assertEqual(self.out("read", URL7), f"free\t{URL7}")
        self.repo("main")
        self.assertEqual(self.out("read", "-C", str(self.work)), "no card")

    def test_session_start(self):
        self.repo("claude/session")

        def payload(sid):
            return json.dumps({"session_id": sid, "cwd": str(self.work), "source": "startup",
                               "hook_event_name": "SessionStart"})
        rc, out, _ = self.cs("session-start", stdin=payload("7777777700001111"))
        self.assertEqual((rc, out), (0, ""), "an uncontested start says nothing")
        self.assertEqual(self.ncomments(), 1, "but it still claims")
        rc, out, _ = self.cs("session-start", stdin=payload("8888888800001111"))
        o = json.loads(out)
        self.assertEqual(o["hookSpecificOutput"]["hookEventName"], "SessionStart")
        ctx = o["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("## WARNING: this branch is already claimed\n\nsession `77777777`"))
        self.assertIn(f"The claim is a stamp on {URL7}, refreshed", ctx)
        self.assertEqual(self.cs("session-start", stdin="not json")[:2], (0, ""))

    def test_usage(self):
        rc, _, err = self.cs("bogus")
        self.assertEqual(rc, 2)
        self.assertIn("usage: claim-stamp", err)

    # -- card claims ---------------------------------------------------------
    def test_card_claims(self):
        rc, _, _ = self.cs("card-claim", CARD, "1111111100002222")
        self.assertEqual(rc, 0)
        files = list(self.ledger.iterdir())
        self.assertEqual(len(files), 1, "one ledger entry")
        key = subprocess.run(["cksum"], input=CARD.encode(), capture_output=True).stdout.split()[0].decode()
        self.assertEqual(files[0].name, f"{key}-11111111.tsv", "the ledger file is named by cksum(1)")
        self.assertRegex(files[0].read_text(),
                         r"\A" + re.escape(CARD) + r"\t11111111\t[0-9]{10}\thost-[0-9a-f]{6}\t[0-9]+\n\Z")
        self.assertEqual(self.ncomments(), 1, "and one stamp on the issue")
        self.assertRegex(self.out("card-claims"), r"\Alive\t11111111\thost-[^\t]+\t0m\t" + re.escape(CARD) + r"\Z")
        rc, _, err = self.cs("card-claim", CARD, "3333333300004444")
        self.assertEqual(rc, 1, "a second session is refused")
        self.assertRegex(err, r"^taken: session `11111111` on `host-[0-9a-f]{6}` claimed " + re.escape(CARD) + " 0m ago")
        self.assertEqual(self.ncomments(), 1)
        self.assertEqual(self.cs("card-claim", CARD, "1111111100002222")[0], 0, "the holder may claim again")
        self.assertEqual(self.ncomments(), 1, "patching its stamp, not posting")
        self.cs("card-release", CARD, "1111111100002222")
        self.assertEqual(self.out("card-claims", CARD), "")
        self.assertEqual(self.ncomments(), 0)
        self.assertIn("removed claimed", self.labels())

    def test_card_claim_without_github(self):
        log = "log/2026-09-01-note.md"
        self.assertEqual(self.cs("card-claim", log, "5555555500006666", PATH="/usr/bin:/bin")[0], 0)
        self.assertEqual(self.ncalls(), 0, "ledger only, no network")
        self.assertRegex(self.out("card-claims", log), r"^live\t55555555")
        self.age_ledger("55555555")
        self.assertRegex(self.out("card-claims", log), r"^stale\t55555555")
        self.assertEqual(self.cs("card-claim", log, "7777777700008888")[0], 0, "a stale claim does not block")
        self.assertEqual(list(self.ledger.glob("*-55555555.tsv")), [], "which collects it")
        self.cs("card-release", log)
        self.assertEqual(self.out("card-claims", log), "", "release with no sid frees every claim")

    def test_card_takeover_wrapup_and_lock(self):
        self.cs("card-claim", CARD, "1111111100002222")
        self.age_ledger("11111111")
        self.cs("card-claim", CARD, "3333333300004444")
        self.assertEqual(self.ncomments(), 1, "taking over a stale claim drops its stamp")
        self.cs("release", "--scan", "3333333300004444")
        self.assertEqual(self.out("card-claims", CARD), "", "/wrapup's release drops the card claim")
        self.assertEqual(self.ncomments(), 0)
        key = subprocess.run(["cksum"], input=CARD.encode(), capture_output=True).stdout.split()[0].decode()
        lock = self.tmpd / f"claim-stamp-card-{key}.lock.d"
        lock.mkdir()
        (lock / "meta").write_text(f"pid={os.getpid()}\nhostname={os.uname().nodename}\n")
        rc, _, err = self.cs("card-claim", CARD, "1111111100002222")
        self.assertEqual(rc, 1, "a take mid-claim is refused")
        self.assertIn("being claimed right now", err)
        self.assertEqual(self.cs("card-claim", "", "")[0], 1)
        self.assertEqual(self.cs("card-release")[0], 1)

    def test_refresh_bumps_card_claims(self):
        self.cs("card-claim", CARD, "1111111100002222")
        self.age_ledger("11111111")
        self.cs("refresh", "1111111100002222")
        self.assertRegex(self.out("card-claims", CARD), r"^live\t11111111", "refresh keeps a card claim live")


if __name__ == "__main__":
    unittest.main()
