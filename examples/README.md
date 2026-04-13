This directory contains charms that you can pack and deploy locally, to help learn how to use Ops.

### Charm from the machine charm tutorial

- **[machine-tinyproxy](machine-tinyproxy)** - From [Write your first machine charm](https://documentation.ubuntu.com/ops/latest/tutorial/write-your-first-machine-charm/). This charm demonstrates how to run a reverse proxy with a configurable URL path.

### Charms from the Kubernetes charm tutorial

- **[k8s-1-minimal](k8s-1-minimal)** - From [Create a minimal Kubernetes charm](https://documentation.ubuntu.com/ops/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/create-a-minimal-kubernetes-charm/). This charm is a minimal Kubernetes charm for a demo web server.

- **[k8s-2-configurable](k8s-2-configurable)** - From [Make your charm configurable](https://documentation.ubuntu.com/ops/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/make-your-charm-configurable/). This charm has an option for configuring the web server's port.

- **[k8s-3-postgresql](k8s-3-postgresql)** - From [Integrate your charm with PostgreSQL](https://documentation.ubuntu.com/ops/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/integrate-your-charm-with-postgresql/). This charm can be integrated with a PostgreSQL charm, so that the web server can retrieve database credentials and connect to the database.

- **[k8s-4-action](k8s-4-action)** - From [Expose operational tasks via actions](https://documentation.ubuntu.com/ops/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/expose-operational-tasks-via-actions/). This charm has an action for viewing the database credentials.

- **[k8s-5-observe](k8s-5-observe)** - From [Observe your charm with COS Lite](https://documentation.ubuntu.com/ops/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/observe-your-charm-with-cos-lite/). This charm can be integrated with the [COS Lite](https://charmhub.io/cos-lite) observability stack.

### Other demo charms

- **[httpbin-demo](httpbin-demo)** - A Kubernetes charm for [kennethreitz/httpbin](https://github.com/kennethreitz/httpbin) that demonstrates how to restart the workload when a configuration option changes. To try the charm:

    ```
    charmcraft pack
    juju deploy ./httpbin-demo_amd64.charm --resource httpbin-image=kennethreitz/httpbin
    ```
