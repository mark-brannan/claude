"""The one home for making identifiers, for every entity (work items,
roll stamps, and the rest). Imported, never run directly; stdlib only.

Holds the roll stamp so far. bin/card-id (shell) still makes the work-item id;
when it is rewritten in Python its logic moves here, and the other entities'
id code follows, so no tool formats an id of its own. Name functions with
get / create / new, never mint (a concept for prose, not an identifier).
Card 17910884757abba648.
"""


def get_roll_stamp(now):
    """The curia roll's entry stamp for a datetime: UTC to the second, as
    `20261002t054107z`. The caller passes an aware UTC time."""
    return now.strftime("%Y%m%dt%H%M%Sz")
