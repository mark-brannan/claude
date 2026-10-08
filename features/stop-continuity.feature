Feature: stop-continuity.py, the Stop hook

  Each scenario is one row of the acceptance table in
  hooks/stop-continuity-requirements.md, and its title starts with the row's
  id as `row <id>`, so the id is in the test's name (the join the table asks for).
  tests/test_acceptance_ids.py checks the join both ways. A row whose Given
  holds an `or` is a Scenario Outline, one example per fixture. The steps
  run the hook as Claude Code does: a subprocess fed a Stop event on stdin,
  in a scratch HOME and TMPDIR with a fake gh first on PATH
  (tests/conftest.py).

  Scenario Outline: row 0.1 any input, including none
    Given <input> on the hook's stdin
    When the Stop hook runs
    Then it exits 0

    Examples:
      | input                   |
      | nothing                 |
      | text that is not JSON   |
      | an event with no fields |

  Scenario Outline: row 1.1 an event with no transcript_path, or one that does not exist
    Given a Stop event for a session in a worked repo
    And the event <lacks>
    When the Stop hook runs
    Then nothing is written under the state dir

    Examples:
      | lacks                                 |
      | has no transcript_path                |
      | names a transcript that does not exist |

  Scenario: row 1.2 an event with no session_id
    Given a Stop event for a session in a worked repo
    And the event has no session_id
    When the Stop hook runs
    Then nothing is written under the state dir

  Scenario: row 3.1 metrics/live/<id>.json exists
    Given a Stop event for a session in a worked repo
    And the session's metrics/live/<id>.json exists
    When the Stop hook runs
    Then the session's metrics/live/<id>.json is gone

  Scenario: row 6.9 cwd outside any repo
    Given a Stop event whose cwd is outside any repo
    When the Stop hook runs
    Then the verdict is "not archivable: not a git repo"
