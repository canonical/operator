(interface-tests)=
# Interface tests
> See also: {ref}`manage-interfaces`

Interface tests are tests that verify the compliance of a charm with an interface specification.
Interface specifications, stored in {ref}`charm-relation-interfaces <charm-relation-interfaces>`, are contract definitions that mandate how a charm should behave when integrated with another charm over a registered interface.

Interface tests will allow `charmhub` to validate the integrations of a charm and verify that your charm indeeed supports "the" `ingress` interface and not just an interface called "ingress", which happens to be the same name as "the official `ingress` interface v2" as registered in charm-relation-interfaces (see [here](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2)).

Also, they allow alternative implementations of an interface to validate themselves against the contractual specification stored in charm-relation-interfaces, and they help verify compliance with multiple versions of an interface.

An interface test is a contract test powered by {ref}``Scenario` <scenario>` and a pytest plugin called [`pytest-interface-tester`](https://github.com/canonical/pytest-interface-tester). An interface test has the following pattern: 
1) **GIVEN** an initial state of the relation over the interface under test
2) **WHEN** a specific relation event fires
3) **THEN** the state of the databags is valid (e.g. it satisfies an expected pydantic schema)

On top of databag state validity, one can check for more elaborate conditions.

A typical interface test will look like:

```python
from interface_tester import Tester

def test_data_published_on_changed_remote_valid():
    """This test verifies that if the remote end has published  valid data and we receive a db-relation-changed event, then the schema is satisfied."""
    # GIVEN that we have a relation over "db" and the remote end has published valid data
    relation = Relation(endpoint='db', interface='db',
                        remote_app_data={'model': '"bar"', 'port': '42', 'name': '"remote"', },
                        remote_units_data={0: {'host': '"0.0.0.42"', }})
    t = Tester(State(relations=[relation]))
    # WHEN the charm receives a db-relation-changed event
    state_out = t.run(relation.changed_event)
    # THEN the schema is valid
    t.assert_schema_valid()
```

This allows us to, independently from what charm we are testing, determine if the behavioural specification of this interface is complied with.


