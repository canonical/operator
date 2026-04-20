# Ops Tools

A collection of tools to use when developing and maintaining Ops charms.

## charmcraft.yaml generation

The definition of charm configuration options and actions should have a single source of truth. Our preference is that truth is in the charm code: this is in an expressive language (Python), that allows more complex type definitions and validation than possible in the Juju config schema language or action parameter JSONSchema. However, Juju and Charmcraft need to find these schema in the `charmcraft.yaml` file.

The package provides tooling to generate the appropriate `charmcraft.yaml` sections for `config` and `actions` from config and action classes in the charm Python code.

### Usage

`ops-tools` ships three command-line tools:

* `update-charmcraft-schema` — read `charmcraft.yaml`, splice in generated `config:` / `actions:` sections, and either print the result to stdout (default) or write it back in place with `--update`.
* `generate-juju-config` — write `config.yaml`-shaped YAML for the given class(es) to stdout. Useful for ad-hoc inspection, piping into other tooling, or driving from a `charmcraft` override-build part.
* `generate-juju-actions` — the same, but for `actions.yaml`.

#### update-charmcraft-schema

By default, the generated YAML is printed to stdout. Use `--update` to modify `charmcraft.yaml` in place.

For example, if your charm contains a single config class in `src/charm.py` called `Config` and three actions, which all end with 'Action' (and no other classes have that name):

```bash
update-charmcraft-schema --config Config --action '.+Action'
```

To update the file in place:

```bash
update-charmcraft-schema --config Config --action '.+Action' --update
```

If you have a config class in `src/workload.py` called `WorkloadConfig` and one in `src/charm.py` called `AdditionalConfig`:

```bash
update-charmcraft-schema --config src.workload:WorkloadConfig --config src.charm:AdditionalConfig
```

This command can be included in a pre-commit configuration, or CI workflow, to ensure that the `charmcraft.yaml` file is always in sync with the Python classes.

#### generate-juju-config / generate-juju-actions

These tools take one or more class specifiers and write the corresponding Juju YAML to stdout. They never read or modify `charmcraft.yaml`.

```bash
generate-juju-config Config
generate-juju-actions '.+Action'
generate-juju-config src.workload:WorkloadConfig src.charm:AdditionalConfig > config.yaml
```

### Example output

The config class:

```python
@dataclasses.dataclass(frozen=True, kw_only=True)
class MyConfig:
    my_str: str = "foo"
    '''A string value.'''
    my_secret: ops.Secret | None = None
    '''A user secret.'''
```

would generate this YAML:

```yaml
config:
    options:
        my-str:
            type: string
            default: foo
            description: A string value.
        my-secret:
            type: secret
            description: A user secret.
```

And the action class:

```python
class Compression(enum.Enum):
    GZ = 'gzip'
    BZ = 'bzip2'

@dataclasses.dataclass(frozen=True, kw_only=True)
class RunBackupAction:
    '''Backup the database.'''

    filename: str
    '''The name of the backup file.'''
    compression: Compression = Compression.GZ
    '''The type of compression to use.'''
```

would generate this YAML:

```yaml
actions:
    run-backup:
        description: Backup the database.
        params:
            filename:
                type: string
                description: The name of the backup file.
            compression:
                type: string
                description: The type of compression to use.
                default: gzip
                enum: [gzip, bzip2]
        required: [filename]
        additionalProperties: false
```

Type annotations for all classes must use the modern `a | b` and `a | None` form, rather than `Union[a, b]` or `Optional[a]`.
