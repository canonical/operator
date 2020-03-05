#!/usr/bin/env python3

import subprocess


def run_command(command):
    print(f"Running command {command.split()}")
    subprocess.call(command, shell=True)


def main():
    print('''
    Welcome to charming!

    Lets get you started...
    ''')

    charm_name = input("Whats the charm called?")
    setup_charm_dir(charm_name)
    initialise_tree(charm_name)

    k8s_charm = input("Is this a k8s charm? y/n")
    if k8s_charm.lower() == "y":
        print("Linking hooks/start")
        run_command("ln -s ../src/charm.py hooks/start")
    else:
        run_command("ln -s ../src/charm.py hooks/install")
        print("Linking hooks/install")
    create_charmpy(charm_name)


def setup_charm_dir(charm_name):
    run_command(f"mkdir {charm_name}")
    run_command(f"cd {charm_name}")
    run_command("git init")


def initialise_tree(charm_name):
    run_command("mkdir hooks src lib mod")
    run_command("touch metadata.yaml config.yaml")
    run_command("git submodule add https://github.com/canonical/operator mod/operator")
    run_command("ln -s ../mod/operator/ops lib/ops")


def create_charmpy(charm_name):
    charm_py = """
import sys
sys.path.append('lib')
from ops.charm import CharmBase
from ops.main import main


class MyCharm(CharmBase):
    pass


if __name__ == "__main__":
    main(MyCharm)

"""

    with open('src/charm.py', 'w') as fh:
        fh.write(charm_py)


if __name__ == "__main__":
    main()
