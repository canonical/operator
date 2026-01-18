(manage-secrets)=
# How to manage secrets
> See first: {external+juju:ref}`Juju | Secret <secret>`, {external+juju:ref}`Juju | Manage secrets <manage-secrets>`, {external+charmcraft:ref}`Charmcraft | Manage secrets <manage-secrets>`

> Added in `Juju 3.0.2`

This document shows how to use secrets in a charm -- both when the charm is the secret owner as well as when it is merely an observer.

## Secret owner charm

> By its nature, the content in this section only applies to *charm* secrets.

### Add and grant access to a secret

Before secrets, the owner charm might have looked as below:

```python
class MyDatabaseCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.database_relation_joined, 
                               self._on_database_relation_joined)

    ...  # other methods and event handlers
   
    def _on_database_relation_joined(self, event: ops.RelationJoinedEvent):
        event.relation.data[self.app]['username'] = 'admin' 
        event.relation.data[self.app]['password'] = 'admin'  # don't do this at home   
```

With secrets, this can be rewritten as:

```python
class MyDatabaseCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.database_relation_joined,
                               self._on_database_relation_joined)

    ...  # other methods and event handlers

    def _on_database_relation_joined(self, event: ops.RelationJoinedEvent):
        content = {
            'username': 'admin',
            'password': 'admin',
        }
        secret = self.app.add_secret(content)
        secret.grant(event.relation)
        event.relation.data[self.app]['secret-id'] = secret.id
```

Note that:
- We call `add_secret` on `self.app` (the application). That is because we want the secret to be owned by this application, not by this unit. If we wanted to create a secret owned by the unit, we'd call `self.unit.add_secret` instead.
- The only data shared in plain text is the secret ID (a locator URI). The secret ID can be publicly shared. Juju will ensure that only remote apps/units to which the secret has explicitly been granted by the owner will be able to fetch the actual secret payload from that ID.
- The secret needs to be granted to a remote entity (app or unit), and that always goes via a relation instance. By passing a relation to `grant` (in this case the event's relation), we are explicitly declaring the scope of the secret -- its lifetime will be bound to that of this relation instance.

If the relation is a cross-model relation, Juju only allows the offering application to grant access to secrets.

> See more: [](ops.Application.add_secret)

### Create a new secret revision

To create a new secret revision, the owner charm must call `secret.set_content()` and pass in the new payload:

```python
class MyDatabaseCharm(ops.CharmBase):

    ... # as before

    def _rotate_webserver_secret(self, secret):
        content = secret.get_content()
        secret.set_content({
            'username': content['username'],              # keep the same username
            'password': _generate_new_secure_password(),  # something stronger than 'admin'
        })
```

This will inform Juju that a new revision is available, and Juju will inform all observers tracking older revisions that a new one is available, by means of a `secret-changed` hook.

```{caution}
If your charm creates new revisions, it **must** also add a handler for the `secret-remove` event, and call `remove_revision` in it. If not, old revisions will continually build up in the secret backend. See more: {ref}`howto-remove-a-secret`
```

### Change the rotation policy or the expiration date of a secret

Typically you want to rotate a secret periodically to contain the damage from a leak, or to avoid giving hackers too much time to break the encryption.

A charm can configure a secret, at creation time, to have one or both of:

- A rotation policy (weekly, monthly, daily, and so on).
- An expiration date (for example, in two months from now).

Here is what the code would look like:

```python
class MyDatabaseCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.secret_rotate,
                               self._on_secret_rotate)

    ...  # as before

    def _on_database_relation_joined(self, event: ops.RelationJoinedEvent):
        content = {
            'username': 'admin',
            'password': 'admin',
        }
        secret = self.app.add_secret(content,
            label='secret-for-webserver-app',
            rotate=SecretRotate.DAILY)

    def _on_secret_rotate(self, event: ops.SecretRotateEvent):
        # this will be called once per day.
        if event.secret.label == 'secret-for-webserver-app':
            self._rotate_webserver_secret(event.secret)
```

Or, for secret expiration:

```python
class MyDatabaseCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.secret_expired,
                               self._on_secret_expired)

    ...  # as before

    def _on_database_relation_joined(self, event: ops.RelationJoinedEvent):
        content = {
            'username': 'admin',
            'password': 'admin',
        }
        secret = self.app.add_secret(content,
            label='secret-for-webserver-app',
            expire=datetime.timedelta(days=42))  # this can also be an absolute datetime

    def _on_secret_expired(self, event: ops.SecretExpiredEvent):
        # this will be called only once, 42 days after the relation-joined event.
        if event.secret.label == 'secret-for-webserver-app':
            self._rotate_webserver_secret(event.secret)
```

(howto-remove-a-secret)=
### Remove a secret

To remove a secret (effectively destroying it for good), the owner needs to call `secret.remove_all_revisions`. Regardless of the logic leading to the decision of when to remove a secret, the code will look like some variation of the following:

```python
class MyDatabaseCharm(ops.CharmBase):
    ...

    # called from an event handler
    def _remove_webserver_secret(self):
        secret = self.model.get_secret(label='secret-for-webserver-app')
        secret.remove_all_revisions()
```

After this is called, the observer charm will get a `ModelError` whenever it attempts to get the secret. In general, the presumption is that the observer charm will take the absence of the relation as indication that the secret is gone as well, and so will not attempt to get it.

### Remove a single secret revision

Removing a single secret revision is a more common (and less drastic!) operation than removing all revisions. If your charm creates new revisions of secrets, it **must** implement a `secret-remove` handler that calls `remove_revision`.

Typically, the owner will remove a secret revision when it receives a `secret-remove` event -- that is, when that specific revision is no longer tracked by any observer. If a secret owner did remove a revision while it was still being tracked by observers, they would get a `ModelError` when they tried to get the secret.

A typical implementation of the `secret-remove` event would look like:

```python
class MyDatabaseCharm(ops.CharmBase):

    ...  # as before

    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.secret_remove,
                               self._on_secret_remove)

    def _on_secret_remove(self, event: ops.SecretRemoveEvent):
        # All observers are done with this revision, remove it:
        event.remove_revision()
```

### Revoke a secret

For whatever reason, the owner of a secret can decide to revoke access to the secret to a remote entity. That is done by calling `secret.revoke`, and is the inverse of `secret.grant`.

An example of usage might look like:

```python
class MyDatabaseCharm(ops.CharmBase):

    ...  # as before

    # called from an event handler
    def _revoke_webserver_secret_access(self, relation):
        secret = self.model.get_secret(label='secret-for-webserver-app')
        secret.revoke(relation)
```

Just like when the owner granted the secret, we need to pass a relation to the `revoke` call, making it clear what scope this action is to be applied to.

## Secret observer charm

> This applies to both charm and user secrets, though for user secrets the story starts with the charm defining a configuration option of type `secret`, and the secret is not acquired through relation data but rather by the configuration option being set to the secret's URI.
>
> A secret owner charm is also an observer of the secret, so this applies to it too.

### Start tracking the latest secret revision

Before secrets, the code in the secret observer charm may have looked something like this:

```python
class MyWebserverCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.database_relation_changed,
                               self._on_database_relation_changed)

    ...  # other methods and event handlers

    def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
        username = event.relation.data[event.app]['username']
        password = event.relation.data[event.app]['password']
        self._configure_db_credentials(username, password)
```

With secrets, the code would become:

```python
class MyWebserverCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.database_relation_changed,
                               self._on_database_relation_changed)

    ...  # other methods and event handlers

    def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
        secret_id = event.relation.data[event.app]['secret-id']
        secret = self.model.get_secret(id=secret_id)
        content = secret.get_content()
        self._configure_db_credentials(content['username'], content['password'])
```

Note that:
- The observer charm gets a secret via the model (not its app/unit). Because it's the owner who decides who the secret is granted to, the ownership of a secret is not an observer concern. The observer code can rightfully assume that, so long as a secret ID is  shared with it, the owner has taken care to grant and scope the secret in such a way that the observer has the rights to inspect its contents.
- The charm first gets the secret object from the model, then gets the secret's content (a dict) and accesses individual attributes via the dict's items.

> See more: [](ops.Secret.get_content)

### Label the secrets you're observing

Sometimes a charm will observe multiple secrets. In the `secret-changed` event handler above, you might ask yourself: How do I know which secret has changed?
The answer lies with **secret labels**: a label is a charm-local name that you can assign to a secret. Let's go through the following code:

```python
class MyWebserverCharm(ops.CharmBase):

    ...  # as before

    def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
        secret_id = event.relation.data[event.app]['secret-id']
        secret = self.model.get_secret(id=secret_id, label='database-secret')
        content = secret.get_content()
        self._configure_db_credentials(content['username'], content['password'])

    def _on_secret_changed(self, event: ops.SecretChangedEvent):
        if event.secret.label == 'database-secret':
            content = event.secret.get_content(refresh=True)
            self._configure_db_credentials(content['username'], content['password'])
        elif event.secret.label == 'my-other-secret':
            self._handle_other_secret_changed(event.secret)
        else:
            pass  # ignore other labels (or log a warning)
```

As shown above, when the web server charm calls `get_secret` it can specify an observer-specific label for that secret; Juju will attach this label to the secret at that point. Normally `get_secret` is called for the first time in a relation-changed event; the label is applied then, and subsequently used in a secret-changed event.

Labels are unique to the charm (the observer in this case): if you attempt to attach a label to two different secrets from the same application (whether it's the on the observer side or the owner side) and give them the same label, the framework will raise a `ModelError`.

Whenever a charm receives an event concerning a secret for which it has set a label, the label will be present on the secret object exposed by the framework.

The owner of the secret can do the same. When a secret is added, you can specify a label for the newly-created secret:

```python
class MyDatabaseCharm(ops.CharmBase):

    ...  # as before

    def _on_database_relation_joined(self, event: ops.RelationJoinedEvent):
        content = {
            'username': 'admin',
            'password': 'admin',
        }
        secret = self.app.add_secret(content, label='secret-for-webserver-app')
        secret.grant(event.relation)
        event.relation.data[event.unit]['secret-id'] = secret.id
```

If a secret has been labelled in this way, the charm can retrieve the secret object at any time by calling `get_secret` with the "label" argument. This way, a charm can perform any secret management operation even if all it knows is the label. The secret ID is normally only used to exchange a reference to the secret *between* applications. Within a single application, all you need is the secret label.

So, having labelled the secret on creation, the database charm could add a new revision as follows:

```python
    def _rotate_webserver_secret(self):
        secret = self.model.get_secret(label='secret-for-webserver-app')
        secret.set_content(...)  # pass a new revision payload, as before
```

> See more: [](ops.Model.get_secret)

#### When to use labels

When should you use labels? A label is basically the secret's *name* (local to the charm), so whenever a charm has, or is observing, multiple secrets you should label them. This allows you to distinguish between secrets, for example, in the `SecretChangedEvent` shown above.

Most charms that use secrets have a fixed number of secrets each with a specific meaning, so the charm author should give them meaningful labels like `database-credential`, `tls-cert`, and so on. Think of these as "pets" with names.

In rare cases, however, a charm will have a set of secrets all with the same meaning: for example, a set of TLS certificates that are all equally valid. In this case it doesn't make sense to label them -- think of them as "cattle". To distinguish between secrets of this kind, you can use the [`Secret.unique_identifier`](ops.Secret.unique_identifier) property.

Note that [`Secret.id`](ops.Secret.id), despite the name, is not really a unique ID, but a locator URI. We call this the "secret ID" throughout Juju and in the original secrets specification -- it probably should have been called "uri", but the name stuck.

### Peek at a new secret revision

Sometimes, before reconfiguring to use a new credential revision, the observer charm may want to peek at its contents (for example, to ensure that they are valid). Use `peek_content` for that:

```python
    def _on_secret_changed(self, event: ops.SecretChangedEvent):
        content = event.secret.peek_content()
        if not self._valid_password(content.get('password')):
           logger.warning('Invalid credentials! Not updating to new revision.')
           return
        content = event.secret.get_content(refresh=True)
        ...
```

> See more: [](ops.Secret.peek_content)

### Start tracking a different secret revision

To update to a new revision, the web server charm will typically subscribe to the `secret-changed` event and call `get_content` with the "refresh" argument set (refresh asks Juju to start tracking the latest revision for this observer).

```python
class MyWebserverCharm(ops.CharmBase):
    def __init__(self, *args, **kwargs):
        ...  # other setup
        self.framework.observe(self.on.secret_changed,
                               self._on_secret_changed)

    ...  # as before

    def _on_secret_changed(self, event: ops.SecretChangedEvent):
        content = event.secret.get_content(refresh=True)
        self._configure_db_credentials(content['username'], content['password'])
```

> See more: [](ops.Secret.get_content)


## Write tests for your charm

Provide mocked secret content to your charm tests using [](ops.testing.Secret)
objects. For example:

```python
state_in = testing.State(
    secrets={
        testing.Secret(
            tracked_content={'key': 'public'},
            latest_content={'key': 'public', 'cert': 'private'},
        )
    }
)
```

The only mandatory argument to `Secret` is the `tracked_content` dict: a
`str:str` mapping representing the content of the revision. If there is a
newer revision of the content than the one the unit that's handling the event is
tracking, then `latest_content` should also be provided - if it's not, then
Ops assumes that `latest_content` is the `tracked_content`. If there are other
revisions of the content, simply don't include them: the unit has no way of
knowing about these.

In your charm tests, specify the access that units have been granted to the
secret. There are three cases:

- the secret is owned by this app but not this unit, in which case this charm
  can only manage it if we are the leader
- the secret is owned by this unit, in which case this charm can always manage
  it (leader or not)
- (default) the secret is not owned by this app nor unit, which means we can only view it (this includes user secrets)

Thus by default, the secret is not owned by **this charm**, but, implicitly, by
some unknown 'other charm' (or a user), and that other has granted us view
rights.

```{note}
If this charm does not own the secret, but also it was not granted view rights
by the (remote) owner, you model this by _not adding it to State.secrets_! The
presence of a `Secret` in `State.secrets` means, in other words, that the
charm has view rights (otherwise, why would we put it there?). If the charm owns
the secret, or is leader, it will _also_ have manage rights on top of view ones.
```

To specify a secret owned by this unit (or app):

```python
rel = testing.Relation('web')
state_in = testing.State(
    secrets={
        testing.Secret(
            {'key': 'private'},
            owner='unit',  # or 'app'
            # The secret owner has granted access to the "remote" app over some relation:
            remote_grants={rel.id: {'remote'}}
        )
    }
)
```

When handling the `secret-expired` and `secret-remove` events, the charm must
remove the specified revision of the secret. For `secret-remove`, the revision
will no longer be in the `State`, because it's no longer in use (which is why
the `secret-remove` event was triggered). To ensure that the charm is removing
the secret, check the context for the history of secret removal:

```python
class SecretCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.secret_remove, self._on_secret_remove)

    def _on_secret_remove(self, event: ops.SecretRemoveEvent):
        event.remove_revision()


ctx = testing.Context(SecretCharm)
secret = testing.Secret({'password': 'xxxxxxxx'}, owner='app')
old_revision = 42
state_out = ctx.run(
    ctx.on.secret_remove(secret, revision=old_revision),
    testing.State(leader=True, secrets={secret})
)
assert ctx.removed_secret_revisions == [old_revision]
```

