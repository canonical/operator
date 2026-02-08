# Claude Code Configuration

This directory contains Claude Code specific configuration for the Ops project.

## Files

### settings.json
Shared project settings for Claude Code sessions. Includes project context, code style preferences, and enabled features. See [the Claude documentation](https://code.claude.com/docs/en/settings) for more information, including about personal settings.

### subagents/
Custom specialised subagents for project-specific tasks:

- **test-runner.md** - Testing specialist
  - Runs appropriate test suites
  - Interprets test failures
  - Suggests fixes and creates tests

- **reviewer.md** - Code review specialist
  - Reviews for backward compatibility
  - Checks type safety and documentation
  - Validates architecture patterns

Note that the code review specialist is used inside of Claude Code; it is not integrated with GitHub like the Copilot PR review tool.

### hooks/
Automation hooks that run in response to events:

- **after-edit.sh** - Automatically runs `tox -e format` after Python files are edited

To disable hooks, set `"enableHooks": false` in settings.json.

## Usage

### Using Subagents
In Claude Code, you can invoke subagents for specialised tasks:
- "Run the test-runner to check my changes"
- "Use the reviewer to review this PR"
