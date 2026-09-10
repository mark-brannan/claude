# stop-continuity.sh: requirements

## Push rate

**The state-repo push must not fire on every Stop, unattended, forever.**
This hook runs on every Stop across every session and container the user
has open, and the sessions themselves are the ones tripping GitHub's own
abuse-rate defenses against automated push volume — self-inflicted, not
adversarial. Some form of throttling, batching, or debouncing the push
(never the commit — that stays cheap and per-Stop, so nothing is ever lost)
is required, not optional tuning.

The specific window and the force-through conditions (session end, an
explicit flush) are tuning and may change without a ruling. What may not
change without one: reverting to an unconditional push per Stop event.
