# Using Extensions

Extensions are how you adapt `agents-cli` to a workflow it doesn't ship with — a different agent framework, an org's deploy policy, or a command of your own — without forking the tool.

---

## What an extension can do

- **Override a built-in command.** Replace what `create`, `run`, `deploy`, or `eval generate` does. Your command-line arguments pass straight through to the replacement, so the command still feels native.
- **Add a new command.** Expose a workflow the tool doesn't have as `agents-cli <your-command>`.

A few things this makes possible:

- **Swap the agent framework** — run the whole lifecycle (`create`, `run`, `eval`, `deploy`) on LangChain instead of ADK. See [First-party extensions](first-party.md).
- **Wrap a command with policy** — run a compliance or SBOM check before the built-in `deploy`.
- **Standardize a team workflow** — commit an `agents-cli-extension.yaml` so everyone (and CI) gets the same overrides.

---

## How extensions work

An extension contributes one thing:

- **Command overrides** — the extension maps a command name to a `run:` vector. When you invoke the command, `agents-cli` runs that vector (no shell) with your arguments appended.

Extensions come from these places: any `org/repo` on GitHub, a first-party shorthand name, or an `agents-cli-extension.yaml` committed at your project root (auto-loaded, no install step). A framework template ships that last kind, so scaffolding from one needs no install.

---

## Adopt an extension

```bash
agents-cli extension add <ref> [--global] [--ref <branch|tag|sha>] [--yes]
agents-cli extension list                 # active extensions, their scope, and the commands they contribute
agents-cli extension update [<name>]      # advance the pin to the latest tracked ref
agents-cli extension remove <name>        # drop it and delete its vendored copy
agents-cli info                        # active extensions, their sources, and any conflicts
```

An overridden or added command is tagged in `agents-cli --help` with `[↑ <extension>]`, and `agents-cli <command> --help` shows its source, scope, and the `run:` vector it executes.

### Reference forms

| Form | Meaning |
|------|---------|
| `acme/acli-extensions` | any `org/repo` on GitHub |
| `acme/acli-extensions#soc2-deploy` | select one extension from a multi-extension repo |
| `local@../my-extension` | a local path (for development) |
| `<name>` | first-party shorthand — resolves to the `google/agents-cli` repo |
| `--ref <branch\|tag\|sha>` | pin a branch, tag, or commit SHA |

---

## Scopes

- **Project (default)** — recorded in this repo's `agents-cli-extensions.yaml`, with the working copy vendored under `extensions/`. It affects **only this project**, and committing both means teammates and CI get the same overrides.
- **User (`--global`)** — stored in `~/.config/agents-cli/` (`%APPDATA%\agents-cli` on Windows). Applies to every project on the machine, and works *before a project exists* — needed to bootstrap an override you need before a project exists.

When both scopes define the same command, **project wins**; `agents-cli info` shows the source.

!!! tip "Prefer project scope"
    A global extension changes commands across every project on the machine. Reach for `--global` only when you need it before a project exists (framework bootstrap) or want it machine-wide.

---

## Trust

First-party extensions added via the shorthand form (`agents-cli extension add <name>`) are trusted automatically. Every `org/repo` reference — including `google/agents-cli` typed out in full — **prompts before install**, since its commands run arbitrary code when invoked. `--yes` skips the prompt (blanket trust — use only for automation and bootstrap).

---

## Lifecycle (lockfile-style)

Extensions pin to an exact commit, like a lockfile:

- **`extension add`** resolves the ref to a commit SHA, records `source` / `ref` / `sha` under `extensions:` in `agents-cli-extensions.yaml`, and vendors a working copy under `extensions/`.
- **`agents-cli install`** re-materializes any missing or stale vendored copy from the pinned SHA, so CI and fresh checkouts get the exact reviewed code — commands and overrides work immediately. It never advances a pin.
- **`extension update [name]`** advances the pin to the latest commit of the **same tracked ref** (e.g. a branch), re-prompting for third-party trust. Nothing updates in the background. To move to a *different* tag, re-run `extension add <ref> --ref <new-tag>`.
- **`extension remove <name>`** drops the entry and deletes the working copy. It acts on one scope per call (project before user), so an extension installed at both scopes needs a second `remove`.

!!! note "Commit both files"
    For a project-scoped extension, commit both the `extensions:` entry in `agents-cli-extensions.yaml` and the vendored copy under `extensions/`. Then it works offline: `agents-cli install` restores the vendored copy and command overrides on a fresh checkout.

---

## Compatibility

An extension can declare the agents-cli range it supports (`requires.agents_cli` — see [Authoring](authoring.md#compatibility)). What you see as a user:

- **`agents-cli extension add` / `update`** refuse an out-of-range install when the extension is `error`-mode (and roll back), so you can't install something that won't run on your CLI. A `warn`-mode extension installs with a warning.
- **After a CLI upgrade** that moves an extension out of its range, nothing breaks: the extension warns, and an `error`-mode one fails with the range and the fix, rather than running the built-in. Run `agents-cli extension update <name>` to pull a version that supports your CLI.
- **`agents-cli extension list` and `agents-cli info`** show each extension's `requires` range and flag any that are `! incompatible` with the running CLI.
