# Golden Principles

Mechanical code standards enforced by the validation gate. Each principle has a check type, pattern, and remediation.

## Max File Size

Keep files under 500 lines to maintain readability and single responsibility.
Check: file_size
Pattern: 500
Remediation: Split into smaller modules. Extract cohesive logic into separate files.

## Require Docstrings for Public Functions

Public functions and classes must have docstrings for discoverability.
Check: regex
Pattern: (def |async def |class )(?!_)[a-zA-Z0-9_]+
Remediation: Add a docstring describing purpose, arguments, and return value.

## No Hardcoded Secrets

API keys, passwords, and tokens must not appear in source.
Check: regex
Pattern: (api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]
Remediation: Use environment variables or a secrets manager. Document in README.

## Consistent Naming

Follow project naming conventions: snake_case for Python, camelCase for TypeScript.
Check: naming
Pattern: ^[a-z][a-z0-9_]*\.py$
Remediation: Rename files to match conventions. Use linter/formatter.
