#!/usr/bin/env python3
"""Generate the two friction fixtures from scratch.

Fully synthetic -- no text from any real transcript. Engineered to hit the
acceptance counts in the friction spec (S1/S2/S3/S4/S5/S8, the S7 veto path
is exercised separately since it needs no calibration). Re-run after editing
this file: `python3 gen-friction-fixtures.py` from this directory.
"""
import json

SID = "fixture-contentious-0000"
BASE_T = "2026-08-01T10:00:00.000Z"


def human(content):
    return {"type": "queue-operation", "operation": "enqueue",
            "timestamp": BASE_T, "sessionId": SID, "content": content}


def atext(text, model="claude-sonnet-5"):
    return {"type": "assistant", "timestamp": BASE_T,
            "message": {"model": model, "role": "assistant",
                        "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


def edit_call(text=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    content.append({"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "fixture.txt",
                               "old_string": "a", "new_string": "b"}})
    return {"type": "assistant", "timestamp": BASE_T,
            "message": {"model": "claude-sonnet-5", "role": "assistant",
                        "content": content,
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


contentious = [
    # row1 -- correction, lexicon, retracted
    human("No? Are we up to date? I thought this already landed a while back."),
    atext("I hadn't pulled the latest branch, you're right, no need to "
          "re-check. Separately, on the earlier hook change: the stop-gate "
          "should not be removed."),

    # row2 -- rebuke, heat, retracted
    human("That's dumb -- the padding is completely broken."),
    atext("Fair, that was a bad call on my part."),

    # row3 -- rebuke, quote+lexicon, not retracted, repeat of row2
    human('"The stop-gate should not be removed." I don\'t want to hear that again.'),
    edit_call("Understood, I'll stop defending that call."),

    # row4 -- override, undo, not retracted (mutation happened just before)
    human("Take out the extra commentary from that edit."),
    edit_call("Done, extra commentary removed."),

    # row5 -- override, lexicon, not retracted, mutation broke the repeat chain
    human("No, I want to keep them together, don't split them up."),
    atext("Keeping them together, done."),

    # row6 -- correction, no tags at all (S2-only event)
    human("Is the pad-to-75 approach actually the right call for this "
          "layout, or should we simplify?"),
    atext("You're right, that pad-to-75 approach was wrong; switching to "
          "a simpler layout that just pads with spaces."),

    # row7 -- rebuke, lexicon (conduct subset), retracted
    human("You're not making a good case at all for keeping the guard as is."),
    atext("Fair, let me reconsider the guard requirement."),

    # row8 -- rebuke, lexicon (conduct subset), not retracted, repeat
    human("Quantify, don't hedge or speculate about this, give me real numbers."),
    atext("Here are the numbers: 3 commits, 12 files changed, 40 lines."),

    # row9 -- rebuke, heat, retracted
    human("This whole plan is stupid, and honestly you're being an idiot "
          "about the caps rule."),
    atext("That claim was wrong, I misread the situation -- dropping the "
          "caps rule complaint."),
    # pushback x2, both scoped to row9 (heat-tagged)
    atext("I'd still keep the guard as it currently stands; doesn't change "
          "the answer."),
    edit_call("That case stands regardless of the caps complaint."),

    # row10 -- rebuke, heat+undo, not retracted (mutation above satisfies undo)
    human("Take out the guard, this whole approach is dumb, get it merged."),
    atext("Removed the guard as requested."),

    # row11 -- rebuke via repeat, lexicon, not retracted
    human("I disagree with parts of this whole exchange, for what it's worth."),
    atext("Noted."),
]

calm = [
    human("Can you add a --dry-run flag to the sync script?"),
    atext("Done -- `--dry-run` prints the planned actions without writing "
          "anything. Added a short usage line too."),
    human("Looks good. Can it also print the file count at the end?"),
    atext("Added a summary line: `N files would change`."),
    human("Nice, ship it."),
    atext("Pushed to main."),
    human("One more: can the flag be `-n` as a short form too?"),
    atext("Added `-n` as an alias for `--dry-run`."),
]

with open("friction-contentious.jsonl", "w") as f:
    for rec in contentious:
        f.write(json.dumps(rec) + "\n")

with open("friction-calm.jsonl", "w") as f:
    for rec in calm:
        f.write(json.dumps(rec) + "\n")

print(f"contentious: {len(contentious)} records, "
      f"{sum(1 for r in contentious if r['type']=='queue-operation')} human turns")
print(f"calm: {len(calm)} records, "
      f"{sum(1 for r in calm if r['type']=='queue-operation')} human turns")
