#!/usr/bin/env bash

CURRENT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

tmux bind-key S display-popup -E "python3 $CURRENT_DIR/scripts/main.py"
