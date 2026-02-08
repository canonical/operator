(tutorial)=
# Tutorials

Writing a machine charm is not so different from writing a Kubernetes charm, but it *is* a little bit different. As such, our tutorial comes in two basic flavors, for machines and for Kubernetes. The choice is yours!

## Write a machine charm

This tutorial guides you through writing a machine charm that runs a reverse proxy. The tutorial covers typical functionality of a charm, including configuration.

```{toctree}
:maxdepth: 1

write-your-first-machine-charm
```

## Write a Kubernetes charm

This tutorial guides you through writing a Kubernetes charm for an application. The tutorial covers typical functionality of a charm, including configuration, relations, and actions.

```{toctree}
:maxdepth: 1

from-zero-to-hero-write-your-first-kubernetes-charm/index
```

## Write a charm for a 12-factor application

To charm a 12-factor style application, you're able to build a charm by running a Charmcraft command and making a few modifications to the provided content. The Charmcraft tutorials are a great entry point for anyone new to making charms, particularly anyone building or managing applications that use these frameworks:

* {external+charmcraft:ref}`Write your first Kubernetes charm for a Django app <write-your-first-kubernetes-charm-for-a-django-app>`
* {external+charmcraft:ref}`Write your first Kubernetes charm for an Express app <write-your-first-kubernetes-charm-for-a-expressjs-app>`
* {external+charmcraft:ref}`Write your first Kubernetes charm for a FastAPI app <write-your-first-kubernetes-charm-for-a-fastapi-app>`
* {external+charmcraft:ref}`Write your first Kubernetes charm for a Flask app <write-your-first-kubernetes-charm-for-a-flask-app>`
* {external+charmcraft:ref}`Write your first Kubernetes charm for a Go app <write-your-first-kubernetes-charm-for-a-go-app>`
