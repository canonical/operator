#!/bin/bash

# A script to get you started charming!

git init
touch .gitignore
touch metadata.yaml
mkdir mod lib src hooks
git submodule add https://github.com/canonical/operator mod/operator
ln -s ../mod/operator/ops lib/ops


cat <<END > src/charm.py
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)

     def on_start(self, event):
        # Handle the event here.
END
