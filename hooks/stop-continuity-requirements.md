# stop-continuity.sh: requirements

## Push rate

The state-repo push to the remote must not fire on every Stop hook.
Throttle, batch, or debounce in some form. The local commit is not
affected since it stays per-Stop, so nothing is lost.

The window and the force-through conditions are tuning and can change
freely. Removing the throttle entirely cannot.

Note that the GitHub recommended limit (6 pushes per minute per repo) must
account for all of our pushes combined and we should strive to stay far
below this limit.
https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits
