"""The one home for making identifiers, for every entity (work items,
roll stamps, and the rest). Imported, never run directly; stdlib only.

Holds the roll stamp and the work item's id. bin/card-id (shell) is the
command line over both and makes no id of its own; the other entities' id
code follows here, so no tool formats an id of its own. Name functions with
get / create / new, never mint (a concept for prose, not an identifier).
Card 17910884757abba648.

An id has one job: to identify one thing, uniquely. It is opaque: nothing
parses it, nothing is encoded in it. A work item's id is epoch seconds then
eight hex, no separator (1790836842077c62eb); the shape is the record's
(docs/work-item-lifecycle.md, "The identifier") and every reader checks only
the shape. The seconds are the clock, so ids sort by creation; the eight hex
are random (32 bits from the OS), so no two calls agree, in one process or
across any number, with nothing consulted: no session, no counter, no lock,
no look at the store. Two ids made in the same second collide with
probability 2^-32 per pair, and the store's exclusive create refuses the
second (the user, claude#256, 2026-10-22).
"""
import secrets


def get_roll_stamp(now):
    """The curia roll's entry stamp for a datetime: UTC to the second, as
    `20261002t054107z`. The caller passes an aware UTC time."""
    return now.strftime("%Y%m%dt%H%M%Sz")


def new_item_id(now):
    """A fresh work item id at epoch second `now`: the seconds, then eight
    random hex. Every call is new; nothing is read or kept."""
    return f"{int(now)}{secrets.token_hex(4)}"
