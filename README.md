# The Charmed Operator Framework

This Charmed Operator Framework simplifies [operator](https://charmhub.io/about) development
for [model-driven application management](https://juju.is/model-driven-operations).

Operators emerged from the Kubernetes community; an operator is software that drives lifecycle
management, configuration, integration and daily actions for an application. Operators simplify
software management and operations. They capture reusable app domain knowledge from experts in a
software component that can be shared.

This project extends the operator pattern to enable
[charmed operators](https://juju.is/universal-operators), not just for Kubernetes but also
operators for traditional Linux or Windows application management.

Operators use a [Charmed Operator Lifecycle Manager
(Charmed OLM)](https://juju.is/operator-lifecycle-manager) to coordinate their work in a cluster.
The system uses Golang for concurrent event processing under the hood, but enables the operators to
be written in Python.

## Simple, composable operators

Operators should 'do one thing and do it well'. Each operator drives a single microservice and can
be [composed with other operators](https://juju.is/integration) to deliver a complex application.

It is better to have small, reusable operators that each drive a single microservice very well.
The operator handles instantiation, scaling, configuration, optimisation, networking, service mesh,
observability, and day-2 operations specific to that microservice.

Operator composition takes place through declarative integration in the OLM. Operators declare
integration endpoints, and discover lines of integration between those endpoints dynamically at
runtime.

## Pure Python operators

The framework provides a standard Python library and object model that represents the application
graph, and an event distribution mechanism for distributed system coordination and communication.

The OLM is written in Golang for efficient concurrency in event handling and distribution.
Operators can be written in any language. We recommend this Python framework for ease of design,
development and collaboration.

## Better collaboration

Operator developers publish Python libraries that make it easy to integrate your operator with
their operator. The framework includes standard tools to distribute these integration libraries and
keep them up to date.

Development collaboration happens at [Charmhub.io](https://charmhub.io/) where operators are
published along with integration libraries. Design and code review discussions are hosted in the
Charmhub [discourse]. We recommend the [Open Operator Manifesto](https://charmhub.io/manifesto)
as a guideline for high quality operator engineering.

## Event serialization and operator services

Distributed systems can be hard! So this framework exists to make it much simpler to reason about
operator behaviour, especially in complex deployments. The Charmed OLM provides
[operator services](https://juju.is/operator-services) such as provisioning, event delivery,
leader election and model management.

Coordination between operators is provided by a cluster-wide event distribution system. Events are
serialized to avoid race conditions in any given container or machine. This greatly simplifies the
development of operators for high availability, scale-out and integrated applications.

## Model-driven Operator Lifecycle Manager

A key goal of the project is to improve the user experience for admins working with multiple
different operators.

We embrace [model-driven operations](https://juju.is/model-driven-operations) in the Charmed
Operator Lifecycle Manager. The model encompasses capacity, storage, networking, the application
graph and administrative access.

Admins describe the application graph of integrated microservices, and the OLM then drives
instantiation. A change in the model is propagated to all affected operators, reducing the
duplication of effort and repetition normally found in operating a complex topology of services.

Administrative actions, updates, configuration and integration are all driven through the OLM.

# Getting started

A package of operator code is called a charmed operator or “charm. You will use `charmcraft` to
register your operator name, and publish it when you are ready. There are more details on how to
get a complete development environment setup over in the
[documentation](https://juju.is/docs/sdk/dev-setup)

Charmed Operators written using the Charmed Operator Framework are just Python code. The goal
is to feel natural for somebody used to coding in Python, and reasonably easy to learn for somebody
who is not a pythonista.

The dependencies of the operator framework are kept as minimal as possible; currently that's Python
3.5 or greater, and `PyYAML` (both are included by default in Ubuntu's cloud images from 16.04 on).

For a brief intro on how to get started, check out the
[Hello, World!](https://juju.is/docs/sdk/hello-world) section of the documentation!

# Testing your charmed operators

The operator framework provides a testing harness, so you can check your charmed operator does the
right thing in different scenarios, without having to create a full deployment.
`pydoc3 ops.testing` has the details, including this example:

```python
harness = Harness(MyCharm)
# Do initial setup here
relation_id = harness.add_relation('db', 'postgresql')
# Now instantiate the charm to see events as the model changes
harness.begin()
harness.add_relation_unit(relation_id, 'postgresql/0')
harness.update_relation_data(relation_id, 'postgresql/0', {'key': 'val'})
# Check that charm has properly handled the relation_joined event for postgresql/0
self.assertEqual(harness.charm. ...)
```

## Talk to us

If you need help, have ideas, or would just like to chat with us, reach out on
the Charmhub [Mattermost].

We also pay attention to the Charmhub [Discourse]

You can deep dive into the [API docs] if that's your thing.

[discourse]: https://discourse.charmhub.io
[api docs]: https://ops.rtfd.io/
[sdk docs]: https://juju.is/docs/sdk
[mattermost]: https://chat.charmhub.io/charmhub/channels/charm-dev

## Operator Framework development

See [HACKING.md](HACKING.md) for details on dev environments, testing, etc.

