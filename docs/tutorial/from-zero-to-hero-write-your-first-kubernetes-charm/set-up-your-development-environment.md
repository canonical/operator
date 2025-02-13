(set-up-your-development-environment)=
# Set up your development environment

> <small>{ref}`From zero to hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>`  > Set up your development environment</small> 
>
> **See previous: {ref}`Study your application <study-your-application>`**

In this chapter of the tutorial you will set up your development environment. 

You will need a charm directory, the various tools in the charm SDK, Juju, and a Kubernetes cloud. And it’s a good idea if you can do all your work in an isolated development environment. 

You can get all of this by following our generic development setup guide, with some annotations. 

> See the automatic setup instructions in {external+juju:ref}`Juju | Manage your deployment environment <manage-your-deployment-environment>`, with the following changes:
> - At the directory step, call your directory `fastapi-demo`. 
> - At the VM setup step, call your VM `charm-dev` and also set up Docker: 
>     1. `sudo addgroup --system docker`
>     1. `sudo adduser $USER docker`
>     1. `newgrp docker`
>     1. `sudo snap install docker`.
> - At the cloud selection step, choose `microk8s`. 
> - At the mount step: Make sure to read the box with tips on how to edit files locally while running them inside the VM! <br><br>
> All set!



Congratulations, your development environment is now ready! 

> **See next: {ref}`Create a minimal Kubernetes charm <create-a-minimal-kubernetes-charm>`**

