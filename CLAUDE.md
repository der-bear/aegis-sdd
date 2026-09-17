# aegis-sdd — Aegis SDD

This repository is the framework itself. The rules below are its own compiled configuration,
produced from `.aegis/answers.json`; `aegis next` says what the current step is. The `aegis`
command comes from this checkout — run `./install.sh` once if it is not on your PATH.

@.aegis/generated/rules.md

<!-- aegis:pointer — the line above imports the compiled agent rules. If you are an agent and
     this import is missing, run `aegis migrate`. The rules live in .aegis/generated/, which is
     write-protected; change them with `aegis answer <question> <value>`. Restating them here
     is how a pointer file drifts from the configuration it points at. -->
