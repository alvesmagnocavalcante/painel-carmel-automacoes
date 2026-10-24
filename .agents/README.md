# Codex Python Professional

Small, practical Codex guidance for Python, FastAPI and Django.

## Installation (per repository)
1. Copy `AGENTS.md` and `.agents/skills/` to the repository root.
2. If your repository already has `AGENTS.md`, merge rules instead of overwriting.
3. If your repository already has `pyproject.toml`, merge the `[tool.*]` sections instead of overwriting. Update Python target and test paths.
4. Install optional development tools in your existing environment: `python -m pip install ruff pytest pyright` (plus your project test dependencies).
5. Run `ruff check .`, `ruff format --check .`, `pytest -q`, `pyright` as applicable.
6. In Codex, use `$clean-code`, `$python-backend`, `$code-review` or `$safe-refactor` explicitly, or allow matching skills to activate automatically.

## Global setup
For personal defaults across repositories, copy `AGENTS.md` to `~/.codex/AGENTS.md` and the skill folders to `~/.agents/skills/`. Keep project-specific commands and architecture in the repo's own `AGENTS.md`.

## Example prompts
- `$python-backend Implemente o endpoint solicitado com o menor diff possível, seguindo o projeto e cobrindo erros e permissões.`
- `$clean-code Simplifique esta função sem alterar o comportamento. Evite abstrações novas.`
- `$code-review Revise o diff atual. Liste somente problemas concretos, por severidade e com arquivo/linha.`
- `$safe-refactor Refatore este módulo preservando a API pública e os testes existentes.`

## Notes
- These files do not enforce rules by themselves: use CI to enforce lint/tests.
- Ruff, pytest and Pyright require adaptation to existing project dependencies and structure.
- Do not apply Django migrations automatically in production.
