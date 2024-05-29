# Update Charm Pins

## GitHub Actions Usage

Inputs:

- `workflows`: space or newline-separated list of workflow YAML files relative to this repository root
- `gh-pat`: personal access token to query external repositories hosted at GitHub

This action will update the `workflows` in the current checkout. It is the responsibility of the caller
to do something with these changes.

## Local Usage

```command
# set up a venv and install the deps
pip install -r requirements.txt

# set the GITHUB_TOKEN env var with a personal access token
export GITHUB_TOKEN=ghp_0123456789

# run the script
python main.py path-to/.github/workflows/one.yaml path-to/.github/workflows/another.yaml

# check the modifications in the current branch
git diff
```
