(set-up-your-development-environment)=
# Set up your development environment

> <small>{ref}`From zero to hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>`  > Set up your development environment</small> 
>
> **See previous: {ref}`Study your application <study-your-application>`**

In this chapter of the tutorial you will set up your development environment. 

You will need a charm directory, the various tools in the charm SDK, Juju, and a Kubernetes cloud. And it’s a good idea if you can do all your work in an isolated development environment. 

To set all of this up, see {external+juju:ref}`Juju | Manage your deployment environment > Set things up <set-things-up>`, with the following changes: 

- At the directory step, call your directory `fastapi-demo`.
- At the VM setup step, call your VM `charm-dev`. Also set up Docker:
    ```text
    sudo addgroup --system docker
    sudo adduser $USER docker
    newgrp docker
    sudo snap install docker
    ```
- At the cloud selection step, choose `microk8s`.
- At the mount step, read the tips about how to edit files locally while running them inside the VM.

Congratulations, your development environment is ready! 

> **See next: {ref}`Create a minimal Kubernetes charm <create-a-minimal-kubernetes-charm>`**

