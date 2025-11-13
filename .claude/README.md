# Claude Code Configuration

This directory contains Claude Code specific configuration for the Ops project.

## Files

### settings.json
Shared project settings for Claude Code sessions. Includes project context, code style preferences, and enabled features.

### subagents/
Custom specialized subagents for project-specific tasks:

- **test-runner.md** - Testing specialist
  - Runs appropriate test suites
  - Interprets test failures
  - Suggests fixes and creates tests

- **reviewer.md** - Code review specialist
  - Reviews for backward compatibility
  - Checks type safety and documentation
  - Validates architecture patterns

### hooks/
Automation hooks that run in response to events:

- **after-edit.sh** - Automatically runs `tox -e format` after Python files are edited
  - Ensures consistent code formatting
  - Runs automatically on file modifications

## Usage

### Using Subagents
In Claude Code, you can invoke subagents for specialised tasks:
- "Run the test-runner to check my changes"
- "Use the reviewer to review this PR"

### Hooks
Hooks run automatically when enabled in settings.json. The after-edit hook will:
1. Detect when .py files are modified
2. Run `tox -e format` automatically
3. Report formatting results

To disable hooks, set `"enableHooks": false` in settings.json.
