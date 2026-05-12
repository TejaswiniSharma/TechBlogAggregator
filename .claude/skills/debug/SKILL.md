# Debug Skill

Given a bug description, reproduce it, investigate the relevant code, rank hypotheses, then implement and verify the fix.

## Steps

### 1. Reproduce
- Run the exact failing path: hit the endpoint, run the test, or execute the script that triggers the bug.
- Capture the full error output (stack trace, status code, log lines). If no error is visible, add a targeted log or assertion to surface the failure.

### 2. Read all relevant files
- Trace the call path from the entry point (route/handler → service → storage) to where the error originates.
- Read every file in that path — do not skip files to save time.
- Note the exact line numbers where the failure most likely occurs.

### 3. Form 2-3 hypotheses, ranked by likelihood
State each hypothesis as: **what is wrong → why it would cause this symptom**.

Example format:
1. **(Most likely)** FTS5 delete uses NEW content instead of OLD — causes index desync on update
2. **(Possible)** Missing NULL guard on optional field — causes AttributeError only when field is absent
3. **(Less likely)** Race condition on concurrent writes — causes intermittent failures under load

### 4. Implement the fix
- Fix the highest-likelihood hypothesis first.
- Make the smallest change that addresses the root cause — no refactoring beyond the fix.
- If the fix is non-obvious, add a one-line comment explaining *why* (not *what*).

### 5. Verify
- Re-run the original reproduction steps and confirm the error is gone.
- Run the full test suite to check for regressions: `pytest` (Python) or `dotnet test` (C#).
- If the bug had no test before, write a minimal regression test that would have caught it.

## Example invocation

> /debug When saving a note, the app returns 500. The note is saved to the DB but the FTS index is out of sync afterward.

Claude will:
1. Curl `POST /api/notes` with a test payload and capture the 500 response
2. Read `web/app.py → save_note()`, `storage.py`, and the FTS schema
3. List hypotheses (e.g. FTS delete using new content, missing row guard, wrong column name)
4. Patch the highest-likelihood cause
5. Re-curl the endpoint, run `pytest`, confirm green
