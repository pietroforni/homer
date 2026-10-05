# Safety model

Homer follows the same pipeline for every terminal request:

1. Ask Ollama for one structured, single-line command proposal.
2. Reject malformed model output.
3. Check syntax with `/bin/zsh -n` and parse supported shell syntax.
4. Classify the command and display the exact proposal and explanation.
5. Require `Execute? [y/N]`; pressing Enter means no.
6. Run `/bin/zsh -lc` only after an explicit yes.

High-risk patterns are always blocked. These include privilege escalation, broad recursive
deletion, disk formatting, raw device writes, destructive `find`, remote scripts piped into a
shell, dynamic shell evaluation, command substitution, shutdown, and broad permission changes.

Lower-risk state-changing commands such as `rm`, `mv`, output redirection, network access, or
package installation receive a visible caution but can be confirmed.

The checks are deliberately conservative and cannot prove that a command is harmless. Use
`--dry-run` for unfamiliar requests, inspect quoted paths, and perform sensitive administration
tasks manually.
