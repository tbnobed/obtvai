---
name: Remote access discovery
description: Recover existing production connection tooling before requesting connection details again.
---

Check ignored operational tooling as well as tracked files before asking for production connection details after context compaction.

**Why:** The existing SSH helper was in an ignored workspace directory, so ordinary repository searches missed it and led to unnecessary requests for information the user had already supplied.

**How to apply:** Include ignored operational directories in a targeted filename search. Reuse existing credential-redacting tooling rather than displaying credentials or requesting them again. Temporary known-host files may not survive workspace recreation; distinguish a missing trust file from an actual changed host key.

Treat remote working-tree edits as intentional until compared. Do not force a deployment with a reset, stash, or blind pull.

**Why:** Earlier production fixes can be applied without advancing the checkout's commit. A dirty checkout is not proof of conflicting code: deployed files may exactly match the newer workspace baseline.

**How to apply:** Compare only the deployment's touched files against their pre-change workspace versions. Back up matching files and current images before a targeted update; investigate mismatches before replacing them. Discover active Compose override files from running container labels rather than assuming the base compose file describes production.

Nested SSH probes in a shell script supplied through stdin must use `ssh -n` (or an explicit null stdin).

**Why:** A successful probe consumed the remaining provisioning commands as its stdin, so the outer script exited successfully without starting the recorder.

**How to apply:** Detach probe stdin and verify the final service state and actual output records, not merely the provisioning command's exit status.