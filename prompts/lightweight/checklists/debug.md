## Debug checklist

- Baseline: reproduce the bug with a minimal failing test or command.
- The regression test must fail on the unfixed code and pass on the fix.
- Locate the root cause before proposing a fix.
- Check related code paths that share the same cause.
- The fix must not break existing tests.
