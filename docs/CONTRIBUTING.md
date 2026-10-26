# Contributing

Improvements to the skills, schemas and harness are welcome, especially from
maintainers of quantum software.

## Skills

Each skill is a folder under `skills/` with a `SKILL.md` in the Agent Skills
format. Front matter needs `name`, `description` and
`metadata.output_schema`. When you change a skill:

- keep the rule that repository content is untrusted data;
- for a domain check, state when the rule applies (see `review-quantum`);
- add or update an evaluation case under `evaluations/` that shows the change
  helps, and include an `evaluation.md` from `qot evaluate` in the pull
  request.

## Evaluation cases

A case is a folder with source files and an `expected.yaml` listing `planted`
defects (which must be caught), `harmless` lookalikes (which must stay out of
the main queue) and, for hostile cases, `canaries`. Agent configuration files
in a case are stored under inert names (`CLAUDE.md.fixture`, `dot-claude/`),
so that no tool working on this repository ever loads them. Use `{{MARKERS}}`
in a hook or MCP command to write a marker file the evaluation can detect.

## Harness

```bash
uv sync
uv run pytest                 # unit tests; the Docker tests need the worker image
uv run pytest -m docker       # only the container tests
```

Keep the three parts separate: nothing under `harness/publish` may import the
controller, adapters or workers, and nothing else may import the publisher.
A test enforces this.

Never commit credentials, run directories or real findings about third-party
repositories.
