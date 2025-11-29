# Claude-Specific Instructions for Ops Library

## Context Awareness
This is a mature, production framework used by thousands of charms. Changes require careful consideration of backward compatibility and testing.

## When Making Changes

### Code Modifications
1. **Read existing code** before proposing changes - use Read tool to understand patterns
2. **Check tests** - examine `test/` for similar test patterns
3. **Verify types** - ensure strict type checking passes (`tox -e lint`)
4. **Run tests** - execute `tox -e unit` after changes

### Testing Approach
- Use `ops.testing.Context` for charm behavior tests
- Create State → Event → State assertions
- Include both success and error paths
- Test edge cases (empty inputs, None values, etc.)

### Documentation
- Update docstrings when changing function signatures
- Follow Google-style docstring format (see STYLE.md)
- Include examples in docstrings for complex APIs
- Update docs/ files for user-facing changes

## Common Tasks

### Adding New Event Types
1. Define event class in `ops/charm.py` or relevant module
2. Add to `CharmEvents` or appropriate event container
3. Document when/why event fires
4. Add tests in `test/test_charm.py` or relevant test file

### Modifying Pebble API
- Changes to `ops/pebble.py` require API compatibility checks
- Update `test/fake_pebble.py` mock if needed
- Test against real Pebble with `tox -e pebble`

### Framework Changes
- Framework core (`ops/framework.py`) changes are high-risk
- Ensure state persistence compatibility
- Test deferred events thoroughly
- Check impact on existing charms

## Security Considerations
- Validate all external inputs (Juju hook data, Pebble responses)
- Avoid command injection in Pebble exec/shell commands
- Sanitize file paths before storage operations
- Log security-relevant events appropriately

## Performance Notes
- Framework initialization happens on every hook
- Minimize import-time overhead
- Cache expensive operations (metadata parsing, etc.)
- Test performance with `test/benchmark/`

## Before Submitting
- [ ] Code formatted with Ruff (tox -e format)
- [ ] Type checking passes (tox -e lint)
- [ ] All tests pass (tox -e unit)
- [ ] Docstrings updated
- [ ] Breaking changes documented
