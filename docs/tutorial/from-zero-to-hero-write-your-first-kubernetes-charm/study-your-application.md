(study-your-application)=
# Study your application

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Study your application </small>

A charm is an application packaged with all the logic it needs to operate in the cloud.

As such, if you want to charm an application, the first thing you need to understand is the application itself.

Of course, what exactly you'll need to know and how exactly you'll have to go about getting this knowledge will very much depend on the application.

In this part of the tutorial we will choose an application for you and tell you all you need to know about it to start charming. Our demo app is called  'FastAPI Demo' and we have designed it specifically for this tutorial so that, by creating a Kubernetes charm for it, you can master all the fundamentals of Kubernetes charming.


<!--
This tutorial will introduce you to writing a Kubernetes charm with the Juju SDK. You will go through the process of charming the web application.
What does charming and Charmed Operator mean? Charmed Operator means all of the domain knowledge and expertise about an application distilled in clean and maintainable Python code.
Application that we use in current tutorial is based on Python FastAPI framework, utilizes PostgreSQL database and has Prometheus metrics scrape target. Once it is charmed, we will integrate our charm with existing PostgreSQL charm and Canonical Observability Stack (COS) bundle for monitoring purpose.

Before you start charming, it is essential to understand the application that you would like to charm. In this chapter of the tutorial we will thus familiarise ourselves with our demo app.

-->



## Features

The FastAPI app was built using the Python [FastAPI](https://fastapi.tiangolo.com/) framework to deliver a very simple web server. It offers a couple of API endpoints that the user can interact with.

The app also has a connection to a  [PostgreSQL](https://www.postgresql.org/) database. It provides users with an API to create a table with user names, add a name to the database, and get all the names from the database.

Additionally, our app uses [starlette-exporter](https://pypi.org/project/starlette-exporter/) to generate real-time application metrics and to expose them via a `/metrics` endpoint that is designed to be scraped by [Prometheus](https://prometheus.io/).

Finally, every time a user interacts with the database, our app writes logging information to the log file and also streams it to `stdout`.

To summarize, our demo application is a minimal but real-life-like application that has external API endpoints, performs database read and write operations, and collects real-time metrics and logs for observability purposes.


## Structure

The app source code is hosted at https://github.com/canonical/api_demo_server .

As you can see [here](https://github.com/canonical/api_demo_server/tree/master/api_demo_server), the app consists of primarily the following two files:

- `app.py`, which describes the API endpoints and the logging definition, and
- `database.py`, which describes the interaction with the PostgreSQL database.

Furthermore, as you can see [here](https://github.com/canonical/api_demo_server/tree/master?tab=readme-ov-file#configuration-via-environment-variables), the application provides a way to configure the output logging file and the database access points (IP, port, username, password) via environment variables:

- `DEMO_SERVER_LOGFILE`
- `DEMO_SERVER_DB_HOST`
- `DEMO_SERVER_DB_PORT`
- `DEMO_SERVER_DB_USER`
- `DEMO_SERVER_DB_PASSWORD`


## API endpoints

The application is set up such that, once deployed, you can access the deployed IP on port 8000. Specifically:


|||
|-|-|
| To get Prometheus metrics: | `http://<IP>:8000/metrics` |
| To get a Swagger UI to interact with API: |`http://<IP>:8000/docs`|

<!--
`http://<IP>:8000/metrics` - to get Prometheus metrics
`http://<IP>:8000/docs` - to get a Swagger UI to interact with API
-->

## OCI image

Our app's OCI image is at

https://github.com/canonical/api_demo_server/pkgs/container/api_demo_server

<!--
If you want to proceed with your own copy of an image please proceed with the following instruction.

Since charm framework operates around OCI images we need to build and publish our image.

You can inspect `Dockerfile` in the root of the app directory. We will build our image using docker on top of ubuntu:22.04 base. Later push it to GitHub container registry (ghcr).

```
# Log in using environment variables for GitHub username and API token
docker login ghcr.io --username $gh_user --password=$ghcr_token

# Build image, execute from the directory with `Dockerfile`
docker build -t api_demo_server .

# tag an image with ghcr tag and version.
# Specify your username and repo name where to push
docker tag api_demo_server ghcr.io/beliaev-maksim/api_demo_server:1.0.0

# now push your image to web host
docker push ghcr.io/beliaev-maksim/api_demo_server:1.0.0

```
-->


> **See next: {ref}`Set up your development environment <set-up-your-development-environment>`**
