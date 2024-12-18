(publish-your-charm-on-charmhub)=
# Publish your charm on Charmhub

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Pushing your charm to Charmhub</small>
> 
> **See previous: {ref}`Open a Kubernetes port in your charm  <open-a-kubernetes-port-in-your-charm>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```text
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 11_open_port_k8s_service
```

````

In this tutorial you've done a lot of work, and the result is an increasingly functional charm.

You can enjoy this charm on your own, or pass it around to friends, but why not share it with the whole world?

The Canonical way to share a charm publicly is to publish it on  [Charmhub](https://charmhub.io/). Aside from making your charm more visible, this also means you can deploy it more easily, as Charmhub is the default source for `juju deploy`. Besides, Charmcraft is there to support you every step of the way. 

In this chapter of the tutorial you will use Charmcraft to release your charm on Charmhub.


## Log in to Charmhub

```{caution}

**You will need an Ubuntu SSO account.** <br>
If you don't have one yet, sign up on https://login.ubuntu.com/+login

```

```{note}

Logging into Charmhub is typically a simple matter of running `charmcraft login` . However, here we are within a Multipass VM, so we have to take some extra steps.

```


On your Multipass VM, run the code below:

```bash
ubuntu@charm-dev:~/fastapi-demo$ charmcraft login --export ~/secrets.auth
```

Once you've put in your login information, you should see something similar to the output below:

```text
Opening an authorization web page in your browser.
If it does not open, please open this URL:
 https://api.jujucharms.com/identity/login?did=48d45d919ca2b897a81470dc5e98b1a3e1e0b521b2fbcd2e8dfd414fd0e3fa96
```

Copy-paste the provided web link into your web browser. Use your Ubuntu SSO to log in.

When you're done, you should see in your terminal the following:

```text
Login successful. Credentials exported to '~/secrets.auth'.
```

Now set an environment variable with the new token:

```bash
export CHARMCRAFT_AUTH=$(cat ~/secrets.auth)
```

Well done, you're now logged in to Charmhub!

## Register your charm's name

On your Multipass VM, generate a random 8-digit hexadecimal hash, then view it in the shell:

```text
random_hash=$(cat /dev/urandom | tr -dc 'a-f0-9' | head -c 8)
echo "Random 8-digit hash: $random_hash"
```
```{important}

Naming your charm is usually less random than that. However, here we are in a tutorial setting, so you just need to make sure to pick a unique name, any name.

```

Navigate to the `charmcraft.yaml` file of your charm and update the `name` field with the randomly generated name.

Once done, prepare the charm for upload by executing `charmcraft pack` . This command will create a compressed file with the updated name prefix, as discussed earlier.

Now pass this hash as the name to register for your charm on Charmhub:

```bash
$ charmcraft register <your random hash name>
Congrats! You are now the publisher of '<your random hash name>'
```

You're all set!

## Upload the charm and its resources

On your Multipass VM, run the code below. (The argument to `charmcraft upload` is the filepath to the `.charm` file.)

```text
charmcraft upload <your random hash name>_ubuntu-22.04-amd64.charm
Revision 1 of <your random hash name> created
```

```{note}

Every time a new binary is uploaded for a charm, a new revision is created on Charmhub. We can verify its current status easily by running `charmcraft revisions <charm-name>`.

```


Now upload the charm's resource -- in your case, the `demo-server-image` OCI image specified in your charm's `charmcraft.yaml` as follows:

<!--
To upload the image Charmcraft will first check if that specific image is available in Canonical's Registry, and just use it if that's the case. If not, it will try to get it from the developer's local OCI repository (needs `dockerd` to be installed and running)
-->

First, pull it locally:

```text
docker pull ghcr.io/canonical/api_demo_server:1.0.1
```

Then, take note of the image ID:

```text
docker images ghcr.io/canonical/api_demo_server
```

This should output something similar to the output below:

```text
REPOSITORY                          TAG       IMAGE ID       CREATED        SIZE
ghcr.io/canonical/api_demo_server   1.0.1     <image-id>   6 months ago   532MB 
```

Finally, upload the image as below, specifying first the charm name, then the image name, then a flag with the image digest:

```text
charmcraft upload-resource <your random hash name> demo-server-image --image=<image-id>
```

Sample output:

```text
Revision 1 created of resource 'demo-server-image' for charm '<your random hash name>'.
```

All set!

## Release the charm

Release your charm as below. 

```{important}

**Do not worry:**<br>
While releasing a charm to Charmhub gives it a public URL, the charm will not appear in the Charmhub search results until it has passed formal review. 

```


```text
$ charmcraft release <your random hash name> --revision=1 --channel=beta --resource=demo-server-image:1
Revision 1 of charm '<your random hash name>` released to beta
```

This releases it into a channel so it can become available for downloading.

Just in case, also check your charm's status:

```text
$ charmcraft status <your random hash name>
Track    Base                  Channel    Version    Revision    Resources                                                                                                                    
latest   ubuntu 22.04 (amd64)  stable     -          -           -                                                                                                                            
                               candidate  -          -           -                                                                                                                            
                               beta       1          1           demo-server-image (r1)                                                                                                       
                               edge       ↑          ↑           ↑
```

Congratulations, your charm has now been published to charmhub.io! 

You can view it at any time at `charmhub.io/<your random hash name>`.



