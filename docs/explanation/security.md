(security)=

# Security

When producing security documentation for your charm, it's important to consider the security aspects of the charm's dependencies. If there are any security questions that aren't answered here in terms of the use of cryptographic technology, security risks, hardening, and good practice, with regards to Ops, please reach out to the Charm Tech team, and we'll do our best to assist.

## Cryptographic technology

The only case where Ops uses cryptography is for sending trace data, when a certificate authority provider has been integrated with the charm. This is done using HTTPS, using either TLS 1.2 or 1.3, using the implementation provided by the standard library of the Python that is executing the charm. See [tracing security](#ops_tracing_security) for more details.

There is no use of hashing or digital signatures.

## Inter-process communication

Ops communicates with Juju by reading environment variables and running processes in the charm environment (hook commands).

> See also:
> - {external+juju:ref}`Juju | Hook <hook>`
> - {external+juju:ref}`Juju | Hook command <list-of-hook-commands>`

## Hardening

Hardening a charm that uses Ops is done in the same way as any other charm: no extra hardening steps are required as a result of using Ops.

> See also: {external+juju:ref}`Juju | Harden your deployment <harden-your-deployment>`

## Charm unit databases

Ops stores state in a sqlite3 database named `.unit-state.db`. This database includes [](ops.StoredState) objects and the defer notice queue.

> See also:
>  - [](#storedstate-uses-limitations)
>  - [](#how-and-when-to-defer-events)

The state database is in the charm directory, which is set by Juju in the `JUJU_CHARM_DIR` environment variable and typically looks like `/var/lib/juju/agents/unit-my-unit-0/charm`. For a machine charm, this directory is on the unit's machine. For a Kubernetes charm, this directory is in the charm container.

Ops sets the permissions for the state database to allow only reading and writing by the user running the charm. You shouldn't try to edit this file or change its permissions.

Ops buffers tracing data in a sqlite3 database named `.tracing-data.db` in the same directory as the state database. Trace data is stored in this database only if the `tracing` extra is installed. When `tracing` is installed, Ops buffers tracing data even if tracing has not been enabled through an integration with a trace receiver (this allows collecting traces prior to the integration).

For example, the permissions of the databases are:

```text
-rw-r--r--  1 root root  32K Jul 13 23:48 .tracing-data.db
-rw-------  1 root root  20K Jul 13 23:48 .unit-state.db
```

## ops[testing]

When testing an event with [](ops.testing.Context), the mocked unit state database and tracing data are stored in memory. Each event creates a new charm directory, which is provided by [](tempfile.TemporaryDirectory).

## Security updates

We strongly recommend restricting the version of `ops` (and `ops[harness,testing,tracing]` in your `dev` dependencies) in `pyproject.toml` in a way that allows picking up new compatible releases every time that you re-lock. If your charm needs to support Ubuntu 20.04 (with Python 3.8), then this looks like `ops~=2.23`. Otherwise, this looks like `ops~=3.0`. Set a minor version that includes all the features that the charm uses.

Your charm repository should have tooling configured so that any dependencies with security updates are detected automatically (such as [Dependabot](https://docs.github.com/en/code-security/dependabot/dependabot-security-updates/about-dependabot-security-updates) or [Renovate](https://www.mend.io/renovate/)), prompting to you re-lock so that the charm will be built with the latest version.

For information about supported versions and how to report security issues, see [SECURITY.md](https://github.com/canonical/operator/blob/main/SECURITY.md).

## Risks

Ops inherits the risks of Juju executing charms (for example, injecting data into the charm context or through the use of hook commands). Charm authors should be familiar with {external+juju:ref}`Juju security <juju-security>` and {external+pebble:ref}` Pebble security <security>`.

If a charm is integrated with a tracing receiver, Ops introduces the risk of outgoing traces being intercepted. Traces should not include any sensitive data, but intercepted traces can provide information about the structure of the charm and the events that the charm has processed. In addition, an attacker that blocked trace data could hide malicious activity.

Otherwise, Ops doesn't introduce any new security risks. Ops does expand the impact of the Juju risk of an attacker gaining access to the filesystem of the charm:

* Access to the deferred notice queue provides information about events that could not be immediately processed (this includes the event name and the event context provided in the hook environment at the time).
* Access to trace data provides detailed information about the implementation of the charm and the events that it has processed. This is particularly the case when tracing has not been configured, as the charm will have a large amount of buffered trace data stored (when tracing is active, this will be regularly sent to the trace receiver and removed from the local database).

## Good practices

* Never include any sensitive data in logs.
* Never include any sensitive data in traces.
* Never include any sensitive data in exceptions.
* Never include any sensitive data in command line arguments (which often end up in logs, traces, or exceptions).
* Use {external+juju:ref}`Juju secrets <secret>` for storing and sharing sensitive data.
* Juju users that integrate a charm with a tracing receiver should also integrate with a certificate authority provider, to ensure all traces are sent via HTTPS.
* Charms should follow best practices for writing secure Python code.
* Machine charms are responsible for setting appropriate ownership and permissions on the files and directories they create, for example using {py:func}`os.umask`.
* Charms should have workflows that statically check for security issues (such as [ruff](https://docs.astral.sh/ruff/linter/) and [zizmor](https://docs.zizmor.sh/)).
* Charm authors should exercise caution when considering adding dependencies to their charms.
* Write the exact dependencies of the charm into a lock file (using `uv lock`, `poetry lock`, or similar tool) and commit that lock file to source control.
* Charm repositories should have tooling that automatically detects outdated dependencies, particularly missing security updates.
* For Kubernetes charms, run the charm as a non-root user when possible (via the {external+charmcraft:ref}`charm-user key in charmcraft.yaml <charmcraft-yaml-key-charm-user>` and specifying the `uid` and `gid` for containers).
* Charm authors should harden their workloads by default. For example, see charm guidance for [postgresql-k8s](https://canonical-charmed-postgresql-k8s.readthedocs-hosted.com/14/explanation/security/), [kubeflow](https://discourse.charmhub.io/t/security/15935), or workload hardening guidance such as [Wordpress](https://developer.wordpress.org/advanced-administration/security/hardening/).
