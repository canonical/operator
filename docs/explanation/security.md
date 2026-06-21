(security)=

# Security

When producing security documentation for your charm, it's important to consider the security aspects of the charm's dependencies. If there are any security questions that aren't answered here in terms of the use of cryptographic technology, security risks, hardening, and good practice, with regards to Ops, please reach out to the Charm Tech team, and we'll do our best to assist.

(ops-product-architecture)=
## Product architecture

Ops sits between Juju and your charm code. Its trust boundaries follow from that position. Juju is the trusted control plane: it provides the hook context that Ops reads, and owns the machine or Kubernetes container where the charm runs.

Ops is a library running inside the charm process under Juju's control. It parses the context that Juju provides, dispatches events to the charm, and persists a small amount of state on the local filesystem. The charm is responsible for application logic, secret handling, and workload configuration.

Ops itself opens no network listeners, manages no credentials, and terminates no TLS — those concerns belong to Juju, the workload, or the charm author.

The diagram below shows where Ops sits and the trust boundaries that follow:

```{mermaid}
flowchart LR
    Juju["Juju agent<br/>(trusted control plane)"]
    subgraph Host["Charm host<br/>(machine or k8s container)"]
        subgraph Process["Charm process"]
            Ops["Ops library"]
            Charm["Charm code"]
        end
        State[("State DB +<br/>trace buffer<br/>(JUJU_CHARM_DIR)")]
    end
    Workload["Workload"]
    Receiver["Tracing receiver"]

    Juju <-->|"hook env, hook commands"| Ops
    Ops <--> Charm
    Charm -->|manages| Workload
    Ops <--> State
    Ops -..->|"HTTPS, only when integrated"| Receiver
```

Juju, on one side of the trust boundary, is the trusted control plane that owns the charm host and supplies the hook context Ops reads. Inside the charm process, Ops is a library invoked by the charm code; both run as the same unprivileged user and share the same filesystem. The state database and trace buffer live in `JUJU_CHARM_DIR` on that filesystem. The only outbound network connection Ops can make on its own is sending buffered trace data over HTTPS, and only when the charm is integrated with a tracing receiver.

(ops-secure-by-design)=
## Secure by design

Ops is designed to keep its security surface small.

Ops only persists a single local state database, plus a local trace buffer when the `tracing` extra is installed. As a result, most of a charm's security posture is determined by Juju, by the workload, and by the charm's own code.

Ops adds no daemons or network listeners of its own; the only outbound connection it can make is sending buffered trace data over HTTPS when a charm is integrated with a tracing receiver. It delegates cryptography to Juju and to the Python standard library rather than implementing its own. It delegates secret storage to Juju secrets.

(ops-cryptographic-technology)=
## Cryptographic technology

The only case where Ops uses cryptography is for sending trace data, when a certificate authority provider has been integrated with the charm. This is done using HTTPS, using either TLS 1.2 or 1.3, using the implementation provided by the standard library of the Python that is executing the charm. See [tracing security](#ops_tracing_security) for more details.

There is no use of hashing or digital signatures.

The cryptographic functionality is provided entirely by the Python standard library. The `ops[tracing]` extra sends data using `urllib.request`, which relies on `ssl` from the standard library, so the TLS implementation and its cipher suites come from the OpenSSL (or equivalent) library that the running Python interpreter was built against. Neither Ops nor the OpenTelemetry packages that the tracing extra depends on (`opentelemetry-api` and `opentelemetry-sdk`) provide any other cryptography implementation.

Ops exposes no cryptographic API to charm authors. Charms that need cryptography should use the Python standard library directly, store sensitive values in {external+juju:ref}`Juju secrets <secret>`, and delegate TLS to Juju (for example, by integrating with a certificate authority provider).

Ops does not encrypt the state database or buffered trace data at rest. Ops restricts the permissions of the state database to the charm user (see [](#ops-charm-unit-databases)), but the contents are stored unencrypted on the local filesystem. For at-rest confidentiality, rely on the host's encryption story: on machine units, encrypt the underlying volume (for example, with LUKS, or the cloud provider's disk encryption); on Kubernetes units, use a storage class backed by an encrypted volume, or enable Kubernetes [encryption at rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/) for the cluster.

## Inter-process communication

Ops communicates with Juju by reading environment variables and running processes in the charm environment (hook commands).

> See also:
> - {external+juju:ref}`Juju | Hook <hook>`
> - {external+juju:ref}`Juju | Hook command <list-of-hook-commands>`

(ops-charm-unit-databases)=
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

## Configuring and operating

### Hardening

Hardening a charm that uses Ops is done in the same way as any other charm: no extra hardening steps are required as a result of using Ops.

> See also: {external+juju:ref}`Juju | Harden your deployment <harden-your-deployment>`

### Logging and monitoring

Charms log through the Python standard library `logging` module. Ops installs a handler that forwards log records to Juju by running the `juju-log` hook command, so charm and framework log messages are collected and surfaced by Juju (for example, through `juju debug-log`) using Juju's own log levels and storage.

Ops also emits structured security events that follow the [OWASP security-logging vocabulary](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html) and Canonical's SSDLC security event logging policy. These events are forwarded to Juju through the same `juju-log` channel, at the Juju `TRACE` level, as JSON.

As a good practice, never write sensitive data to logs (see the Good practices section).

#### Security event schema

Each structured security event is a JSON object with the following fields:

| Field | Description |
| --- | --- |
| `datetime` | UTC timestamp in ISO 8601 format. Duplicates Juju's own timestamp so the event is self-contained when ingested separately. |
| `type` | Always `"security"`, so consumers can filter security events from other structured records. |
| `level` | OWASP severity: `INFO`, `WARN`, or `CRITICAL`. Not the same as the Juju or Python log level. |
| `appid` | `"<model-uuid>-<unit-name>"`, identifying the unit that produced the event. |
| `event` | `"<event_type>:<event_data>"`, where `event_type` is from the OWASP vocabulary (see below). |
| `description` | Free-form human-readable description with details that do not fit in `event`. |

#### Security events emitted by Ops

The following framework-level events are emitted at the OWASP levels shown. They cover the SSDLC stage-1 categories that Ops, as a library, is in a position to detect; access, authentication, and user-management events are the responsibility of Juju and the workload.

| OWASP event | Level | When Ops emits it | SSDLC category |
| --- | --- | --- | --- |
| `sys_crash` | `WARN` | An uncaught exception escapes the charm code. | System Crash |
| `sys_restart` | `WARN` | The charm calls [](ops.Unit.reboot) to reboot the underlying machine. | System Restart |
| `sys_monitor_disabled` | `WARN` | A Pebble check is stopped through [](ops.Container.stop_checks). | System Monitoring Disabled |
| `authz_fail` | `CRITICAL` | A non-leader unit tries to get or set the application status, or a Juju hook command fails with an authorisation-related error. | Unauthorized Access Attempt |

#### Configuring and opting out

Ops itself has no log-stream toggle and no separate monitoring agent: all logging goes through Juju. Verbosity is controlled in Juju, not in Ops or the charm:

* Use `juju model-config logging-config='<root>=WARNING;unit=DEBUG'` (or the equivalent Juju operation) to raise or lower the log level for charm units. Setting a unit log level above `TRACE` filters out the structured security events; this loses the audit trail and is not recommended in production.
* To forward Juju logs to an external monitoring or alerting system, integrate the model with a Juju logging sink (for example, the COS Lite observability stack) rather than configuring anything inside the charm.
* Ops does not provide a built-in mechanism to mask sensitive data in logs. The charm is responsible for never passing secrets, tokens, or other sensitive values into log messages, exceptions, or command-line arguments (see [Good practices](#ops-good-practices)).

## Decommissioning

Ops is a library that runs inside the charm process, so it has no separate lifecycle to decommission. Everything Ops persists lives in the charm directory (`JUJU_CHARM_DIR`): the state database (`.unit-state.db`) and, when the `tracing` extra is installed, the trace buffer (`.tracing-data.db`). Removing the unit through Juju removes the charm directory and so removes Ops's data along with the charm.

If a unit is taken out of service by some means other than `juju remove-unit` (for example, reclaiming the underlying machine or container directly), treat the charm directory the same as any other location that may hold sensitive data, because `StoredState` and buffered deferred-event payloads can contain workload data passed in through events.

## Security lifecycle

Ops is distributed as the `ops` package on [PyPI](https://pypi.org/project/ops/) and follows semantic versioning. Security updates are delivered as new releases on PyPI; charms pick them up by re-locking and rebuilding.

(ops-supported-versions)=
### Supported versions

In line with [SECURITY.md](https://github.com/canonical/operator/blob/main/SECURITY.md), security updates are released for all major versions that have had a release in the last year. A major version that has had no release for over a year is considered end of life. Long Term Support (LTS) releases receive 5 years of support and up to 10 additional years of [extended support](https://ubuntu.com/security/esm).

See the [tool versions page](#tool-versions) for current release dates and end-of-life dates for each supported version. To check which version is installed, run `pip show ops` or `python -c 'import ops; print(ops.__version__)'`.

### Receiving updates

Because Ops is a library, it is updated as part of the charm's normal dependency-management workflow rather than through an in-product auto-update mechanism. The charm author controls when a new version is picked up; the Juju user picks it up by refreshing the charm.

We strongly recommend restricting the version of `ops` (and `ops[harness,testing,tracing]` in your `dev` dependencies) in `pyproject.toml` in a way that allows picking up new compatible releases every time that you re-lock. If your charm needs to support Ubuntu 20.04 (with Python 3.8), then this looks like `ops~=2.23`, which is a Long Term Support (LTS) release. Otherwise, this looks like `ops~=3.0`. Set a minor version that includes all the features that the charm uses.

#### Manually applying an update

To apply a security update by hand:

1. Re-lock dependencies (for example, `uv lock --upgrade-package ops` or `poetry update ops`) to pick up the latest `ops` release that satisfies the version constraint.
2. Rebuild the charm with `charmcraft pack`.
3. Refresh deployed units with `juju refresh <app> --path ./<charm>.charm` (or by uploading the new revision to Charmhub).

#### Scheduling updates

Configure the charm repository so that dependency updates are detected and proposed automatically — for example, with [Dependabot](https://docs.github.com/en/code-security/dependabot/dependabot-security-updates/about-dependabot-security-updates) or [Renovate](https://www.mend.io/renovate/). Combined with a release pipeline, this gives a regular cadence of rebuilt charm revisions with the latest patched `ops`.

#### Postponing updates and the associated risk

Pinning `ops` to an exact version, or disabling automated dependency proposals, postpones updates indefinitely. This means published security fixes for `ops` will not reach your deployed charms until the pin is lifted, the charm is rebuilt, and the unit is refreshed — potentially leaving units exposed to known issues for the entire delay. If you pin for stability or reproducibility reasons, plan a regular cadence to review the pin against the [supported versions](#ops-supported-versions) and the project's release notes.

#### Verifying an update was applied

To check which version of `ops` is running in a deployed unit:

```text
juju ssh <unit> "JUJU_CHARM_DIR=$(ls -d /var/lib/juju/agents/unit-*/charm | head -1); \
    \$JUJU_CHARM_DIR/venv/bin/python -c 'import ops; print(ops.__version__)'"
```

Or, in any environment where the charm's virtualenv is on `PATH`, run `pip show ops` or `python -c 'import ops; print(ops.__version__)'` and compare the result to the version on [PyPI](https://pypi.org/project/ops/).

## Reporting vulnerabilities

If you believe you have found a security vulnerability in `ops`, please report it privately following the instructions in the [`SECURITY.md`](https://github.com/canonical/operator/blob/main/SECURITY.md) file in the project repository.

Reports are handled according to the [Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy), which describes how researchers, users, and customers can responsibly disclose issues to Canonical.

Information about known vulnerabilities affecting `ops` is published in:

* the [GitHub Security Advisories for `canonical/operator`](https://github.com/canonical/operator/security/advisories);
* the [release notes for `ops`](https://github.com/canonical/operator/releases) on GitHub;
* relevant [Ubuntu Security Notices](https://ubuntu.com/security/notices) when a vulnerability also affects an Ubuntu-packaged copy of the library.

## Risks

The risks below follow from the trust boundaries described in [](#ops-product-architecture) and the design choices in [](#ops-secure-by-design); the mitigations are summarised in [](#ops-good-practices).

Ops inherits the risks of Juju executing charms (for example, injecting data into the charm context or through the use of hook commands). Because Juju is the trusted control plane in [](#ops-product-architecture), any compromise of the Juju side propagates into the charm process where Ops runs. Charm authors should be familiar with {external+juju:ref}`Juju security <juju-security>` and {external+pebble:ref}` Pebble security <security>`.

If a charm is integrated with a tracing receiver, Ops introduces the risk of outgoing traces being intercepted — this is the only outbound network connection Ops makes (see [](#ops-product-architecture)). Traces should not include any sensitive data, but intercepted traces can provide information about the structure of the charm and the events that the charm has processed. In addition, an attacker that blocked trace data could hide malicious activity. Mitigation: integrate a certificate authority provider so traces are sent over HTTPS, as noted in [](#ops-good-practices).

Otherwise, Ops doesn't introduce any new security risks. Ops does expand the impact of the Juju risk of an attacker gaining access to the filesystem of the charm — the state database and trace buffer described in [](#ops-charm-unit-databases) are not encrypted at rest (see [](#ops-cryptographic-technology) for the at-rest guidance):

* Access to the deferred notice queue provides information about events that could not be immediately processed (this includes the event name and the event context provided in the hook environment at the time).
* Access to trace data provides detailed information about the implementation of the charm and the events that it has processed. This is particularly the case when tracing has not been configured, as the charm will have a large amount of buffered trace data stored (when tracing is active, this will be regularly sent to the trace receiver and removed from the local database).

(ops-good-practices)=
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
