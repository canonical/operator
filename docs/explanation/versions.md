(tool-versions)=
# Tool versions

When you're deciding which version of tools to use within the charming ecosystem, the base is the key constraint. Once you have selected the base, use the latest supported version of each tool whenever possible.

## Tool versions by base


| Base | Python | Juju | Ops | Charmcraft |
|------|----------------|---------------|--------------|-------------------|
| 18.04 (Bionic Beaver) | [3.6](https://docs.python.org/3/whatsnew/3.6.html) | [2.9](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_2.9.x/) | 1.x | 2.x |
| 20.04 (Focal Fossa) | [3.8](https://docs.python.org/3/whatsnew/3.8.html) | [2.9](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_2.9.x/), [3.6](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_3.6.x/), [4.0](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_4.0.x/juju_4.0.0/) | [2.x](https://documentation.ubuntu.com/ops/2.x/) | 2.x |
| 22.04 (Jammy Jellyfish) | [3.10](https://docs.python.org/3/whatsnew/3.10.html) | [2.9](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_2.9.x/), [3.6](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_3.6.x/), [4.0](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_4.0.x/juju_4.0.0/) | [2.x](https://documentation.ubuntu.com/ops/2.x/), [3.x](https://documentation.ubuntu.com/ops/latest/) | [3.x](https://documentation.ubuntu.com/charmcraft/3.5.3/), [4.x](https://documentation.ubuntu.com/charmcraft/4.0.1/) |
| 24.04 (Noble Numbat) | [3.12](https://docs.python.org/3/whatsnew/3.12.html) | [2.9](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_2.9.x/), [3.6](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_3.6.x/), [4.0](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_4.0.x/juju_4.0.0/) | [2.x](https://documentation.ubuntu.com/ops/2.x/), [3.x](https://documentation.ubuntu.com/ops/latest/) | [3.x](https://documentation.ubuntu.com/charmcraft/3.5.3/), [4.x](https://documentation.ubuntu.com/charmcraft/4.0.1/) |

## Pebble provided by Juju

Each version of Juju provides a fixed version of Pebble. To determine which Pebble features are available to you, look up the Pebble version from the Juju version.

| Juju Version | Pebble Version |
|--------------|----------------|
| 2.9 | [1.1.1](https://github.com/canonical/pebble/releases/tag/v1.1.1) |
| 3.1 | [1.4.2](https://github.com/canonical/pebble/releases/tag/v1.4.2) |
| 3.2 | [1.4.0](https://github.com/canonical/pebble/releases/tag/v1.4.0) |
| 3.3 | [1.4.2](https://github.com/canonical/pebble/releases/tag/v1.4.2) |
| 3.4 | [1.7.4](https://github.com/canonical/pebble/releases/tag/v1.7.4) |
| 3.5 | [1.10.2](https://github.com/canonical/pebble/releases/tag/v1.10.2) |
| 3.6 | [1.26.0](https://github.com/canonical/pebble/releases/tag/v1.26.0) |
| 4.0 | [1.26.0](https://github.com/canonical/pebble/releases/tag/v1.26.0) |

## Support dates for Juju and Ops

Juju releases new minor versions approximately every 3 months, which are supported with bug fixes for four months from their release date and security fixes for another two months. Long Term Support (LTS) releases receive security fixes for 15 years.

> See more: {external+juju:ref}`Juju support timeframes <releasenotes>`

Ops releases new minor versions approximately once per month. Major versions are supported with security fixes for one year from the latest release. To receive bug and security fixes within a major version, charms must update to the latest minor release within that major version.

> See more: [Ops support timeframes](https://github.com/canonical/operator/blob/main/SECURITY.md)

### Juju

| Version | Status | Release Date | End of Bug Fixes | End of Life |
|---------|--------|--------------|-------------------|-------------|
| [Juju 2.9 (LTS)](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_2.9.x/) | <span style="color:green">●</span> Active | 2021-04-28 |  | 2035-04-28 |
| [Juju 3.0](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2022-10-22 | 2023-02-22 | 2023-04-23 |
| [Juju 3.1](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2023-02-06 | 2023-06-06 | 2023-08-06 |
| [Juju 3.2](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2023-05-26 | 2023-09-26 | 2023-11-06 |
| [Juju 3.3](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2023-11-10 | 2024-03-10 | 2024-05-10 |
| [Juju 3.4](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2024-02-15 | 2024-06-15 | 2024-08-15 |
| [Juju 3.5](https://documentation.ubuntu.com/juju/latest/releasenotes/unsupported/juju_3.x.x/) | <span style="color:red">✗</span> EOL | 2024-05-07 | 2024-09-07 | 2024-11-07 |
| [Juju 3.6 (LTS)](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_3.6.x/) | <span style="color:green">●</span> Active | 2024-12-11 |  | 2039-04-11 |
| [Juju 4.0](https://documentation.ubuntu.com/juju/latest/releasenotes/juju_4.0.x/juju_4.0.0/) | <span style="color:green">●</span> Active | 2025-11-14 | 2026-03-14 | 2026-05-14 |

### Ops

| Version | Status | Release Date | End of Life |
|---------|--------|--------------|-------------|
| Ops 1.5 | <span style="color:red">✗</span> EOL | 2020-10-31 | 2024-04-26 |
| Ops 2.23 | <span style="color:orange">⚠</span> Upgrade soon | 2023-01-25 | 2027-02-11 |
| Ops 3.5 | <span style="color:green">●</span> Active | 2026-02-11 | 2027-02-11 |

**Legend:**
- <span style="color:green">●</span> Active: Currently supported
- <span style="color:orange">⚠</span> Upgrade soon: Supported but approaching EOL
- <span style="color:red">✗</span> EOL: End of life, no longer supported
