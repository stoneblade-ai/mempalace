---
name: cortex
description: Cortex — mine projects and conversations into a searchable memory cortex. Use when asked about cortex, memory cortex, mining memories, searching memories, or cortex setup.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Cortex

A searchable memory cortex for AI — mine projects and conversations, then search them semantically.

## Prerequisites

Ensure `cortex` is installed:

```bash
cortex --version
```

If not installed:

```bash
pip install cortex
```

## Usage

Cortex provides dynamic instructions via the CLI. To get instructions for any operation:

```bash
cortex instructions <command>
```

Where `<command>` is one of: `help`, `init`, `mine`, `search`, `status`.

Run the appropriate instructions command, then follow the returned instructions step by step.
