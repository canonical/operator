(study-your-application)=
# Study your application

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Study your application </small>

A charm is an application packaged with all the logic it needs to operate in the cloud.

As such, if you want to charm an application, the first thing you need to understand is the application itself.

Of course, what exactly you'll need to know and how exactly you'll have to go about getting this knowledge will very much depend on the application.

In this part of the tutorial we will choose an application for you and tell you all you need to know about it to start charming. Our demo app is called 'FastAPI Demo' and we have designed it specifically for this tutorial so that, by creating a Kubernetes charm for it, you can master all the fundamentals of Kubernetes charming.

## Features

The FastAPI app was built using the Python [FastAPI](https://fastapi.tiangolo.com/) framework to deliver a very simple web server. It offers a couple of API endpoints that the user can interact with.

The app also has a connection to a [PostgreSQL](https://www.postgresql.org/) database. It provides users with an API to create a table with user names, add a name to the database, and get all the names from the database.

Additionally, our app uses [starlette-exporter](https://pypi.org/project/starlette-exporter/) to generate real-time app metrics and to expose them via a `/metrics` endpoint that is designed to be scraped by [Prometheus](https://prometheus.io/).

Finally, every time a user interacts with the database, our app writes logging information to the log file and also streams it to standard output.

To summarize, our demo app is a minimal but real-life-like app that has external API endpoints, performs database read and write operations, and collects real-time metrics and logs for observability purposes.

## Structure

The [app source](https://github.com/canonical/api_demo_server/tree/master/src/api_demo_server) has the following main files:

- `app.py`, which describes the API endpoints and the logging definition.
- `database.py`, which describes the interaction with the PostgreSQL database.

The app supports environment variables to configure the output logging file and the database connection information:

- `DEMO_SERVER_LOGFILE`
- `DEMO_SERVER_DB_HOST`
- `DEMO_SERVER_DB_PORT`
- `DEMO_SERVER_DB_USER`
- `DEMO_SERVER_DB_PASSWORD`

For more detail about the structure of the app, see https://github.com/canonical/api_demo_server.

## API endpoints

The app is set up such that, once deployed, you can access the deployed IP on port 8000. Specifically:

|||
|-|-|
| Get Prometheus metrics | `http://<IP>:8000/metrics` |
| Get a Swagger UI to interact with the API |`http://<IP>:8000/docs`|
| Get the app's version |`http://<IP>:8000/version`|

## OCI image

https://github.com/canonical/api_demo_server/pkgs/container/api_demo_server%2Fapi-demo-server

> **See next: {ref}`Set up your development environment <set-up-your-development-environment>`**
