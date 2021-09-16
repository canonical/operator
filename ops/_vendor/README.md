
# Vendored libraries

Most libraries can be included via [`requirements.txt`](../../requirements.txt) -- there are a small number included there already. However, this subdirectory exists to hold libraries we need to vendor (copy) into the Python Operator Framework for various reasons.

Care is taken with each library added to Python Operator Framework (either here or using `requirements.txt`), because everything we add increases the size of every charm. We try to use the Python standard library wherever possible.

Below are the libraries we currently vendor.


## websocket-client

[websocket-client](https://github.com/websocket-client/websocket-client), release [v1.2.1](https://github.com/websocket-client/websocket-client/releases/tag/v1.2.1). This is used for the websocket handling required by `pebble.Client.exec()`. The PyPI metadata for this library means it only installs on Python 3.6+, so trying to add it to `requirements.txt` gives an error on Python 3.5. However, its code actually works fine on Python 3.5, so at least while the Python Operator Framework supports Python 3.5, we need to vendor it.
