This directory contains charms that are used as examples in the Ops documentation. **It's currently a work in progress.**

Contents:

- [httpbin-demo](httpbin-demo) - A Kubernetes charm for [kennethreitz/httpbin](https://github.com/kennethreitz/httpbin) that demonstrates how to restart the workload when a configuration option changes. to try the charm:

    ```
    charmcraft pack
    juju deploy ./httpbin-demo_ubuntu-22.04-amd64.charm --resource httpbin-image=kennethreitz/httpbin
    ```

- [k8s-1-minimal](k8s-1-minimal) - The charm constructed in [Create a minimal Kubernetes charm](https://ops.readthedocs.io/en/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/create-a-minimal-kubernetes-charm.html). This charm is a minimal Kubernetes charm for a demo web server.
