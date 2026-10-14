"""The REST reads a tool falls back to where GitHub refuses GraphQL (a Claude
Code cloud session answers HTTP 403). Imported, never run directly; stdlib
only.

The one home for these helpers: bin/prt and bin/pr-blockers use them. Each
takes `run`, a function from gh's argument list to its stdout, because each
tool already decides for itself what a failed gh call means (prt refuses,
pr-blockers exits 2 or reports a rate limit).
"""
import json

NO_GRAPHQL = "GraphQL is not available"


def rest(run, path):
    return json.loads(run(["api", path]) or "null")


def rest_pages(run, path, key=None):
    """Every item of a paged REST list (key names the list inside an object)."""
    out, sep = [], "&" if "?" in path else "?"
    for page in range(1, 31):
        got = rest(run, f"{path}{sep}per_page=100&page={page}")
        got = got[key] if key else got
        out += got
        if len(got) < 100:
            break
    return out


def actor(u):
    """A REST user as GraphQL's author object."""
    u = u or {}
    return {"login": u.get("login"), "__typename": u.get("type")}


def rest_rollup(run, repo, sha):
    """statusCheckRollup's state from the commit's check runs and statuses."""
    runs = rest_pages(run, f"repos/{repo}/commits/{sha}/check-runs", "check_runs")
    states = [("PENDING" if r["status"] != "completed" else
               "SUCCESS" if r["conclusion"] in ("success", "neutral", "skipped") else "FAILURE")
              for r in runs]
    combined = rest(run, f"repos/{repo}/commits/{sha}/status")
    if combined.get("statuses"):
        states.append({"success": "SUCCESS", "failure": "FAILURE", "error": "ERROR"}.get(
            combined["state"], "PENDING"))
    for s in ("FAILURE", "ERROR", "PENDING"):
        if s in states:
            return s
    return "SUCCESS" if states else None
