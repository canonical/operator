---
myst:
  html_meta:
    description: Concrete steps for securing a charm that uses Ops -- handling sensitive data, restricting access, hardening dependencies, and reporting vulnerabilities.
---

(secure-your-charm)=
# How to secure your charm

See first:

- [](#security)
- {external+juju:ref}`Juju | Harden your deployment <harden-your-deployment>`
- {external+pebble:ref}`Pebble | Security <security>`

This guide walks through the actions that a charm author takes to harden a charm that uses Ops, and points to the parts of the [security explanation](#security) that describe why each action matters. Work through the steps that apply to your charm; not every workload needs every step.

## Keep sensitive data out of the observable surface

Ops forwards charm logs to Juju through the `juju-log` hook command, buffers trace data locally, and lets the workload surface information back through hook commands and events. Any of these can end up in operator-visible places -- `juju debug-log`, `juju status`, trace receivers, crash reports, or the state database on disk.

To avoid leaking sensitive data:

- Do not include secrets, tokens, or other sensitive values in log messages, exception messages, or trace attributes.
- Do not pass sensitive values on the command line of processes you run from the charm; they typically end up in logs, traces, or exceptions. Pass them through the environment, a file, or standard input instead.
- Do not put sensitive values into `ops.StoredState`. The state database is not encrypted at rest (see [](#ops-charm-unit-databases)).

Ops does not mask sensitive values for you.

## Store and share sensitive data with Juju secrets

Use {external+juju:ref}`Juju secrets <secret>` for anything that a charm needs to keep confidential -- credentials, tokens, TLS material, and so on. Juju stores the value, controls which units can read it, and rotates access when relations change.

See more: {ref}`manage-secrets`

If your charm accepts a user-provided secret through configuration, define the config option with `type: secret` in `charmcraft.yaml` rather than a plain string.

## Send trace data over HTTPS

When a charm has the `tracing` extra installed and is integrated with a trace receiver, Ops sends buffered trace data over the network. This is the only outbound network connection Ops makes on the charm's behalf.

To avoid traces being intercepted, ensure that Juju users who integrate your charm with a trace receiver also integrate it with a certificate authority provider so that the traffic is TLS-protected. Document this expectation in your charm's own docs.

See more: [](#ops-cryptographic-technology)

## Add static security checks to your project

Configure the checks that your charm project runs before every merge:

- **`ruff`** for Python lint rules, including [`ruff`'s Bandit-derived security rules](https://docs.astral.sh/ruff/rules/#flake8-bandit-s). Enable the `S` rule set in `pyproject.toml`.
- **`zizmor`** for GitHub Actions workflow audits. Configure it to run on every push against the workflow files in `.github/workflows/`.
- **`codespell`** or an equivalent to catch typos in log messages and comments that would otherwise reach operators.

Run these checks in CI so they block merges rather than only running locally.

See more: [](#set-up-ci-integration)

## Keep dependencies patched

Charms pick up security fixes for their dependencies (including Ops itself) at rebuild time, so the release pipeline needs to see new versions promptly. To make that happen:

1. Restrict the version of `ops` in `pyproject.toml` in a way that allows compatible releases to be picked up on the next re-lock, for example `ops~=3.0` (or `ops~=2.23` if you support Ubuntu 20.04). See [](#ops-supported-versions) for the current list of supported releases.
2. Commit a lock file (`uv.lock`, `poetry.lock`, or equivalent) so every rebuild produces a reproducible dependency set.
3. Enable automated dependency updates -- for example, [Dependabot](https://docs.github.com/en/code-security/dependabot/dependabot-security-updates/about-dependabot-security-updates) or [Renovate](https://www.mend.io/renovate/) -- for both Python dependencies and any workflow actions your charm uses.
4. Rebuild and re-release the charm on a regular cadence so that picked-up fixes actually reach deployed units.

Keep the list of runtime dependencies small. Every dependency you add is a dependency you take on responsibility for updating.

## Restrict what the charm can do on its host

Machine charms and Kubernetes charms have different levers here:

**Machine charms.** Set an explicit `os.umask()` before creating files or directories the workload will use, so that group- and world-permissions are not inherited from whatever the calling context happened to be. Set ownership on files and directories the charm creates for the workload user.

**Kubernetes charms.** Prefer running the charm and its sidecar containers as a non-root user. Set the {external+charmcraft:ref}`charm-user key in charmcraft.yaml <charmcraft-yaml-key-charm-user>` to `non-root`, and set an explicit `uid` and `gid` on each container in `charmcraft.yaml`.

## Harden the workload

The workload is separate from Ops and typically has its own security hardening story. Follow the guidance for your workload upstream; if there is no upstream hardening guide, produce one and link to it from the charm's documentation. Existing charm-side examples to model on include:

- [Charmed PostgreSQL on Kubernetes](https://canonical-charmed-postgresql-k8s.readthedocs-hosted.com/14/explanation/security/)
- [Charmed Kubeflow](https://discourse.charmhub.io/t/security/15935)
- [Wordpress Hardening](https://developer.wordpress.org/advanced-administration/security/hardening/) (upstream)

## Verify the version deployed in a unit

To confirm that a running unit has picked up the version of Ops you expect (for example, after a security release):

```text
juju exec --unit <unit> -- bash -c '/var/lib/juju/agents/unit-*/charm/venv/bin/python -c "import ops; print(ops.__version__)"'
```

Compare the result to the [version on PyPI](https://pypi.org/project/ops/). See [](#ops-verifying-update) for background.

## Document the security posture

Include a security section in your charm's own documentation that covers, at a minimum:

- Which workload the charm manages and where its upstream hardening guide lives.
- Which relations the charm requires for a secure deployment (for example, a certificate authority provider for TLS).
- Any configuration options that materially change the security posture (for example, opening extra ports, or relaxing authentication).
- How to report vulnerabilities to you. If your charm repository has a `SECURITY.md`, link to it.

The security explanation for Ops itself lives at [](#security); mirror that structure in your charm if it helps operators reason about the deployment.

## Report vulnerabilities in Ops

If you find a vulnerability in Ops, do not open a public issue. Follow the instructions in [SECURITY.md](https://github.com/canonical/operator/blob/main/SECURITY.md) in the `canonical/operator` repository, which routes reports through the [Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy).
