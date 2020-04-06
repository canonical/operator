# Testing

## Add test folder and test_requirements.txt

In the top level of your charm folder, create a new folder called test and add a file called test_requiments.txt.

Add the following to your test_requirements.txt:

```
# TODO: Update
pyyaml
```

## Creating tests

The operator framework comes with a [testing harness](https://github.com/canonical/operator/pull/146#issue-379532107).


```
class TestMyCharm(unittest.TestCase):
  def setUp(self):
    # possibly we just point the test at the charm's metadata.yaml directly
    self.charm, self.harness = setup_charm(MyCharm, '''
      name: mycharm
      provides:...
      requires:
        foo:
          interface: frob
      ''')

    def test_relation_changed(self):
        rel_id = self.harness.add_relation('foo', 'foo-provider')
        self.harness.add_relation_unit(rel_id, 'foo-provider/0', remote_unit_data={'foo': 'bar'})
        # inspect the initial state of the charm
        self.assertEqual(self.charm.state.foo, 'bar')
        self.harness.update_relation(rel_id, 'foo-provider/0', {'foo':'baz'})
        self.assertEqual(self.charm.state.foo, 'baz')
```

You will find a testing.py file in the Framework.

To test you charm you will need to import this harness along with your other charm imports into a new test file.

```
import sys
import unittest
... other imports e.g.
from src.charm import OSMUIK8sCharm

sys.path.append('lib')
from ops.testing import Harness

```

## Handle interface imports (External Dependencies)

If you use external dependencies such as interface you will have to make sure they are imported to the `lib` directory.

To do this run a symbolic link, similar to this:

`ln -s ../mod/interface-mysql lib/interface_mysql` ensure the folder is valid for Python, and contains a `__init__.py` file.
