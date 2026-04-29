---
myst:
  html_meta:
    description: Publish your charm to Charmhub so that other people can deploy your charm. After you publish your charm, consider how to use tracks and channels appropriately.
---

(publish-your-charm)=
# How to publish your charm on Charmhub

Publishing your charm enables other people to deploy your charm with `juju deploy <charm-name>`. Anyone who knows your charm's name can also see the [Charmhub](https://charmhub.io/) page for your charm.

Before publishing your charm, review the `charmcraft.yaml` file to make sure you've provided appropriate metadata. The metadata controls what appears on the Charmhub page for your charm. See {external+charmcraft:ref}`Charmcraft | Configure package information <configure-package-information>`.

## Publish your charm

To publish your charm, follow the instructions in {external+charmcraft:ref}`Charmcraft | Publish a charm <publish-a-charm>`.

If your charm depends on resources that are binary files, make sure to provide binaries for all the CPU architectures you intend to support.

## Manage tracks and channels

Consider whether you need multiple "tracks" for your charm. By default, you'll have a track called `latest`, which is intended to correspond to the latest version of your charm's workload. Some charm developers choose to have a numbered track instead.

If your charm supports multiple workload versions, you should maintain a track for each version. See {external+charmcraft:ref}`Charmcraft | Manage tracks <manage-tracks>` after publishing your charm.

Charmhub creates four "channels" within each track. By default, you'll have:

- `latest/edge`
- `latest/beta`
- `latest/candidate`
- `latest/stable`

These channels represent different risk levels for users of your charm. Users who deploy your charm from `latest/edge` typically expect to receive a new revision each time you push to your repository's main branch. Users who deploy from `latest/stable` typically expect a numbered release with release notes.

To control which revision of your charm is available from each channel, follow the instructions in {external+charmcraft:ref}`Charmcraft | Manage revisions <manage-charm-revisions>`. You can also use Charmhub to manage revisions.

## Next steps

Published charms don't automatically show up in searches on Charmhub, or general web searches. If your charm is suitable for wider use, you can request public listing. See:

- {ref}`charm-maturity`
- {ref}`make-your-charm-discoverable`
