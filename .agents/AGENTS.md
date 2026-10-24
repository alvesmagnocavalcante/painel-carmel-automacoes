# Engineering rules — Python / FastAPI / Django

## Priorities
1. Correct behavior and security.
2. Readability and simplicity.
3. Maintainability and testability.
4. Performance only when justified by evidence.

## Before editing
- Inspect relevant code, dependencies, conventions and tests.
- Choose the smallest change that solves the request.
- State assumptions only when they materially affect the implementation.
- Do not change unrelated files or public contracts without approval.

## Python
- Follow existing Python version and project conventions; use type hints for public boundaries.
- Prefer standard library and existing dependencies; avoid speculative abstractions.
- Use descriptive names, guard clauses, small cohesive functions and explicit error handling.
- Never swallow exceptions silently or log secrets.
- Do not add classes, repositories, services, factories or interfaces without a concrete need.
- Prefer explicit code to clever one-liners; fewer lines is not the goal.

## FastAPI
- Keep route handlers thin: validation, orchestration and response mapping.
- Use Pydantic models at API boundaries and dependency injection where useful.
- Do not block async endpoints with synchronous I/O; do not use async without need.
- Preserve HTTP status codes, schemas and API compatibility.

## Django
- Prefer Django ORM, forms/serializers and built-in auth/security mechanisms.
- Keep business logic out of views when it becomes nontrivial; avoid unnecessary service layers.
- Prevent N+1 queries with select_related/prefetch_related when relevant.
- Use transactions for multi-write operations requiring atomicity.
- Never create or apply migrations without examining their impact.

## Verification
- Add focused tests for behavior changes and edge cases.
- Run relevant existing tests, Ruff and type checks if configured.
- Report what was run, what failed and what could not be verified.
- Do not claim tests passed unless actually executed.

## Delivery
- Briefly summarize changed behavior, files, tests and remaining risks.
- Avoid lengthy explanations and unrelated refactors.
