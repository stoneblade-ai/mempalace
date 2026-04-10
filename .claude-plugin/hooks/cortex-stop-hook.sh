#!/bin/bash
# Cortex Stop Hook — thin wrapper calling Python CLI
# All logic lives in cortex.hooks_cli for cross-harness extensibility
INPUT=$(cat)
echo "$INPUT" | python3 -m cortex hook run --hook stop --harness claude-code
