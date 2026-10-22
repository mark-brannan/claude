"""The UTC stamp the tools and hooks write ("2026-10-22T11:23:58Z") and the
ways back from it. Imported, never run directly; stdlib only.

The one home for this helper (dotfiles#517); every tool and hook that
stamps a row or reads one back goes through it.
"""
import calendar
import datetime
import time

STAMP = "%Y-%m-%dT%H:%M:%SZ"


def stamp(t=None):
    """The epoch t (now when None) as a UTC stamp, whole seconds."""
    return time.strftime(STAMP, time.gmtime(t))


def unstamp(s):
    """A stamp() string back as an int epoch; ValueError for anything else
    (an offset, fractional seconds, a bare date)."""
    return calendar.timegm(time.strptime(s, STAMP))


def parse(s):
    """An ISO 8601 time, "Z" or an offset, as an aware datetime (naive when s
    carries no zone). ValueError when s is not one; AttributeError when it is
    not a string."""
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def epoch(s):
    """parse(s) as epoch seconds (a float; fractional seconds kept)."""
    return parse(s).timestamp()
