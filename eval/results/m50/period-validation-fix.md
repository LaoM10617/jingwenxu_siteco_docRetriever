# P-041 sentence-final-period fix: local verification

2026-09-27. User approved only this validation freeze exception. Original evaluation and scores remain unchanged at run-20260927-ab-01 (product 7811243, evaluation 859447f, results c5421f2).

Production change: one regex right boundary in backend/app/questions.py. A period followed by a delimiter/end may terminate an explicitly present order ID; a dot followed by an identifier character remains part of the ID. Left boundary, case-sensitive exact lookup and plan validation remain intact.

Regression uses real DocumentService CSV publication/lookup with a fixed local planner and synthetic rows. It verifies both E07/E12 question strings, a dotted ID, and a period followed by another sentence. Existing rejection coverage now also includes internal-dot, decimal-like, slash and left-dot substring cases. This verifies local tools, not live generation or actual catalog values.

- Red: 4 new sentence-period cases failed on original code with invalid_tool_plan.
- Green: python -m pytest backend/tests/test_questions.py -q: 24 passed in 4.60s.
- Full local backend: python -m pytest backend/tests -q: 345 passed in 71.79s.
- git diff --check passed.
- No provider calls, no service restart, no changed evaluation settings or historical result files.

This is a local repair checkpoint, not M5 final acceptance. New live regression needs an approved code/protocol baseline and call budget. E07/E12 are now seen regression cases. Historical reproduction requires the old evaluation commit; the original live runner deliberately rejects changed product code.
