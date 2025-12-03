#!/bin/bash

# Hook that runs after files are edited
# Automatically formats Python files using tox

# Get the list of edited files from the EDIT_FILES environment variable
# EDIT_FILES is a newline-separated list of file paths

if [ -z "$EDIT_FILES" ]; then
    exit 0
fi

# Check if any Python files were edited
python_files_edited=false
while IFS= read -r file; do
    if [[ "$file" == *.py ]]; then
        python_files_edited=true
        break
    fi
done <<< "$EDIT_FILES"

# If Python files were edited, run formatter
if [ "$python_files_edited" = true ]; then
    echo "Python files modified, running formatter..."
    tox -e format

    if [ $? -eq 0 ]; then
        echo "✓ Code formatted successfully"
    else
        echo "⚠ Formatting failed - please check output above"
        exit 1
    fi
fi
