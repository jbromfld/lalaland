# lalaland

Local agent testing workspace for VS Code Copilot harness and a LangChain workflow.

## Local testing focus

This repository is configured to support local iteration for:
- VS Code Copilot harness-driven agent testing
- LangChain-based workflow experimentation

## Copilot cloud agent setup

A `copilot-setup-steps` workflow is included at:
`.github/workflows/copilot-setup-steps.yml`

It prepares Node.js and Python tooling so Copilot cloud agent sessions can run typical harness and LangChain setup steps consistently.
