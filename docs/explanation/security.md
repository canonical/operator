(security)=

# Security

## Cryptographic technology

Ops uses almost no cryptographic technology. Communication with Juju is done via reading environment variables ({external+juju:ref}`Hook <hook>`) and running processes in the charm environment ({external+juju:ref}`Hook command <list-of-hook-commands>`). There is no use of hashing or digital signatures.

The one case where Ops uses cryptography is for sending trace data, when a certificates provider has been integrated with the charm. This is done using HTTPS, using either TLS 1.2 or 1.3, using the implementation provided by the standard library of the Python that is executing the charm. See [tracing - security considerations](#ops_tracing_security) for more details.

## Hardening

Hardening a charm that uses Ops is done in the same way as any other charm: no extra hardening steps are required as a result of using Ops.

## The charm unit databases

Ops stores state ([](ops.StoredState) objects and the defer notice queue) in a sqlite3 database alongside the charm (the unit's machine for machine charms, and the charm container for Kubernetes charms). The database is named `.unit-state.db` and is in the charm directory (this is set by Juju in the `JUJU_CHARM_DIR` environment variable, and typically looks like `/var/lib/juju/agents/unit-my-unit-0/charm`). Ops sets the permissions for the database to allow only reading and writing by the user running the charm. You shouldn't try to edit this file or change its permissions.

Ops buffers tracing data in a sqlite3 database named `.tracing-data.db` in the same directory as the state database. Trace data is stored in this database only if the `tracing` extra is not installed, but even if tracing has not been enabled through an integration with a trace receiver (this allows collecting traces prior to the integration).

For example:

```text
-rw-r--r--  1 root root  32K Jul 13 23:48 .tracing-data.db
-rw-------  1 root root  20K Jul 13 23:48 .unit-state.db
```

## ops[testing]

When testing an event with [](ops.testing.Context), the mocked unit state database and tracing data are stored in memory. Each event creates a new charm directory, which is provided by [](tempfile.TemporaryDirectory).

## Security updates

We strongly recommend pinning `ops` (and `ops[harness,testing,tracing]` in your dev dependencies) in `pyproject.toml` in a way that allows picking up new compatible releases every time that you re-lock. If your charm needs to support Ubuntu 20.04 (with Python 3.8), then this looks like `ops~=2.23`. Otherwise, this looks like `ops~=3.0` (bump the minor number to be high enough that you get all the features that the charm uses).

Your charm repository should have tooling configured so that any dependencies with security updates are detected automatically (such as [Dependabot](https://docs.github.com/en/code-security/dependabot/dependabot-security-updates/about-dependabot-security-updates) or [Renovate](https://www.mend.io/renovate/)), prompting to you re-lock so that the charm will be built with the latest version.

For information about supported versions and how to report security issues, please see [SECURITY.md](https://github.com/canonical/operator/blob/main/SECURITY.md).

## Risks

Using Ops does not introduce any new security risks to charms, unless the charm is integrated with a tracing receiver. It does expand the impact of the Juju risk of an attacker gaining access to the filesystem of the charm:

* Access to the deferred notice queue provides information about events that could not be immediately processed (this includes the event name and the event context provided in the hook environment at the time).
* Access to trace data provides detailed information about the implementation of the charm and the events that it has processed. This is particularly the case when tracing has not been configured, as the charm will have a large amount of buffered trace data stored (when tracing is active, this will be regularly sent to the trace receiver and removed from the local database).

Ops inherits all the risks of Juju executing charms (for example, injecting data into the charm context or through the use of hook commands). Charm authors should be familiar with {external+juju:ref}`Juju security <juju-security>` and {external+pebble:ref}` Pebble security <security>`.

If a charm is integrated with a tracing receiver, this introduces the risk of outgoing traces being intercepted. Traces should not include any sensitive data, but intercepted traces can provide information about the structure of the charm and the events that the charm has processed, and blocking trace data can hide malicious activity.

## Good practices

* Never include any sensitive data in logs.
* Never include any sensitive data in traces.
* Use {external+juju:ref}`Juju secrets <secret>` for storing and sharing sensitive data.
* Juju users that integrate a charm with a tracing receiver should also integrate with a certificate provider, to ensure all traces are sent via HTTPS.
* Charms should follow best practices for writing secure Python code.
* Charms should have workflows that statically check for security issues (such as [ruff](https://docs.astral.sh/ruff/linter/), [bandit](https://bandit.readthedocs.io/en/latest/index.html), and [zizmor](https://docs.zizmor.sh/)).
* Charm authors should exercise caution when considering adding dependencies to their charms.
* Charm repositories should have tooling that automatically detects outdated dependencies, particularly missing security updates.
* For Kubernetes charms, run the charm as a non-root user when possible (via the {external+charmcraft:ref}`charm-user key in charmcraft.yaml <charmcraft-yaml-key-charm-user>` and specifying the `uid` and `gid` for containers).
* Charm authors should harden their workloads by default.
