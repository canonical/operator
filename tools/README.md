# Ops charmcraft.yaml generation tooling

The definition of charm configuration options and actions should have a single
source of truth. Our preference is that truth is in the charm code: this is in
an expressive language (Python), that allows more complex type definitions and
validation than possible in the Juju config schema language or action parameter
JSONSchema. However, Juju and Charmcraft need to find these schema in the
`charmcraft.yaml` file.

This package provides tooling to generate the appropriate `charmcraft.yaml`
sections for `config` and `actions` from config and action classes in the charm
Python code.

For example, the config class:

```python
@dataclasses.dataclass(frozen=True, kw_only=True)
class MyConfig:
    my_bool: bool | None = None
    '''A boolean value.'''
    my_float: float = 3.14
    '''A floating point value.'''
    my_int: int = 42
    '''An integer value.'''
    my_str: str = "foo"
    '''A string value.'''
    my_secret: ops.Secret | None = None
    '''A user secret.'''
```

would generate this YAML:

```yaml
options:
    my-bool:
        type: boolean
        description: A boolean value.
    my-float:
        type: float
        default: 3.14
        description: A floating point value.
    my-int:
        type: int
        default: 42
        description: An integer value.
    my-str:
        type: string
        default: foo
        description: A string value.
    my-secret:
        type: secret
        description: A user secret.
```

And the action classes:

```python
class Compression(enum.Enum):
    GZ = 'gzip'
    BZ = 'bzip2'

@dataclasses.dataclass(frozen=True, kw_only=True)
class RunBackup:
    '''Backup the database.'''

    filename: str
    '''The name of the backup file.'''
    compression: Compression = Compression.GZ
    '''The type of compression to use.'''

@dataclasses.dataclass(frozen=True, kw_only=True)
class AddAdminUser:
    '''Add a new admin user and return their credentials.'''

    username: str
```

would generate this YAML:

```yaml
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

add-admin-user:
    description: Add a new admin user and return their credentials.
    params:
        username:
            type: string
    required: [username]
    additionalProperties: false
```

The Python classes may be:

* Standard library `dataclasses.dataclass` classes.
* Pydantic dataclasses.
* Pydantic `BaseModel` subclasses.
* Other Python classes, as long as TODO

Type annotations for all classes should use the modern `a | b` and `a | None`
form, rather than `Union[a, b]` or `Optional[a]`.
