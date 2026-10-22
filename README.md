# AgentLab Consensus

Three local agents agree on repairs, edit real code, and run real tests. Work on a copy of a project folder or give the team root access to a dedicated WSL distribution.

The team has implementation, review, and testing roles. Every edit and shell command requires all three votes. A veto returns the proposal to the team. Approved changes run your test command automatically, and completion requires passing tests plus unanimous final review.

[Guía en español](README.es.md)

## Quick start

Requires Python 3.11+ and llama.cpp chat servers that support explicit GBNF `grammar` constraints. No Python packages or model weights are bundled. The wizard guides you through using existing servers or loading your own GGUF files by turns on Windows.

```powershell
git clone https://github.com/h0nda1337/agentlab-consensus.git
cd agentlab-consensus
python agentlab.py setup
python agentlab.py folder "C:/my-project" --task "Fix the failing calculation" --test "python -m unittest discover -s tests -v" --apply
```

On Windows you can also double-click `Setup.cmd`. On Linux/macOS the same terminal wizard works; folder mode uses Bash. WSL management and the optional automatic server launcher require Windows. A bare `python agentlab.py` opens setup when no configuration exists.

The four steps cover names, model connections/templates, folder or WSL, and a summary before saving. Existing settings are preserved and backed up. Exiting before saving discards the draft. The connection check reports pending requirements without launching local models. Model messages and the setup UI currently use Spanish.

## Windows desktop · Visual Studio 2019

Double-click `Start-Desktop.cmd` to open the desktop app. When built from source, the first launch compiles it using Visual Studio 2019 or later with **.NET desktop development** installed. To edit it, open `desktop/AgentLab.Desktop.sln` and build Release. It uses WPF and .NET Framework 4.8; the reference assemblies are restored automatically from NuGet. [Microsoft's WPF tutorial for VS 2019](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/get-started/walkthrough-my-first-wpf-desktop-application)

The app includes the four-step setup wizard, GGUF and folder pickers, editable names, model checks, dedicated WSL preparation, a repair form, live proposals/votes/test output, and access to session files. It uses the same Python backend and validation as the terminal. **Choose Python** lets you select your interpreter if automatic detection fails. Python 3.11+ is still required.

**Request stop** waits for the current model response or command to finish, then stops before the next operation and preserves the session. It can take several minutes. A successful result is shown only when the backend reports passing tests and unanimous final approval.

Build and run the automated offscreen checks without opening windows:

```powershell
.\Build-Desktop.ps1 -SelfTest
```

For a portable Windows build that includes the compiled app, see [Releases](https://github.com/h0nda1337/agentlab-consensus/releases). Extract the whole ZIP and run `Start-Desktop.cmd`; Python and your models remain separate prerequisites.

## Rename agents with one command

```powershell
python agentlab.py agents names Atlas Iris Nova
python agentlab.py agents list
python agentlab.py agents rename Atlas Athena
```

`names` takes the implementation, review, and testing names in that order. You can also edit each agent's `display_name` in `config.json`. Names appear in the terminal, shared journal, votes, and model instructions. Endpoints, roles, and stable internal IDs stay linked correctly. Spaces and Unicode are supported; names must be unique.

The internal slots `Dars`, `Rade`, and `Miso` are stable configuration keys. You do not need to rename those keys or any files.

## Dedicated WSL with root access

```powershell
.\setup_repair_wsl.ps1
wsl.exe -d AgentLab-Repair -u root --cd /workspace
# Clone your project into /workspace from this Linux console.
```

Then, from Windows:

```powershell
python agentlab.py wsl --path /workspace/my-project --task "Fix the failing service and add coverage" --test "python3 -m unittest discover -s tests -v"
```

The installer creates a fresh Debian named `AgentLab-Repair`, installs Python/Git/build tools, disables Windows drive automount and normal Windows interop, and validates its settings. It does not clone another distro. Storage defaults to `%LOCALAPPDATA%\AgentLab\WSL`; use `-Location` to choose another drive with at least 4 GB free.

Root can edit Linux system files and install packages. Changes stay in that distribution even if a later step fails. WSL with full root access is **not a security boundary for hostile code**; use a separately managed VM when you need that boundary. [Microsoft's WSL security model](https://wsl.dev/technical-documentation/security/)

## Optional model loading by turns

On a Windows machine that cannot keep three models plus WSL in memory:

Run `python agentlab.py setup` and choose local GGUF loading. Select `llama-server.exe`, each existing GGUF, device (`Vulkan0`, `CUDA0`, or `none` for CPU), and the model template. The wizard creates the private server profiles and links them to your configuration. Use Gemma 2 only for that model family.

Manual configuration remains available through `config.example.json` and `server_profiles.example.json`. Defaults are local ports 8081/8082/8083. Existing external servers can use other base URLs; do not include `/v1`. Automatic loading also accepts `coding.llama_server_path` and `coding.server_profiles_path` for a custom launcher/profile location. Relative profile paths resolve beside the selected config; relative GGUF paths resolve beside the profile file.

The launcher keeps one managed model resident at a time. Small GPU offload is used when commit allows; otherwise it uses CPU. It stops only servers started by the same session, checking ownership, PID, and start time. Other models are left running. This saves memory but can be slow.

## Folder behavior and session files

Folder mode copies current project files, including uncommitted edits. Git metadata, dependency folders, caches, symlinks, and junctions are omitted. Its shell runs with your normal user permissions: the copy is not an OS sandbox.

Without `--apply`, verified edits remain in the working copy. With `--apply`, the original is updated only after final approval, conflict checks, and backups. Publication attempts rollback on copy failure; it is not a crash-proof filesystem transaction.

Sessions are stored in `%LOCALAPPDATA%\AgentLab\repairs` on Windows and `work/repairs` elsewhere. Override with `--runs PATH` **before** the mode:

```powershell
python agentlab.py --runs C:/repair-sessions folder C:/project --task "Fix the bug" --test "npm test"
```

Each session stores the discussion and votes, complete command logs, `result.json`, and changed-file information. Folder sessions also contain the original copy, working copy, backups, and diff. WSL records commands and project content changes; it does not export a complete OS diff.

`--max-steps` limits proposals; `--timeout` limits each command. Failure, a veto, interruption, or the step limit preserves the work and does not report a successful repair. Existing sessions can be inspected but are not automatically resumed.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests cover actual file edits, unanimous approval, vetoes, shell failures, timeouts, conflict prevention, rollback, naming, transport, and server ownership. They use scripted model responses; they do not measure arbitrary model quality.

For the optional real WSL backend test after setup:

```powershell
$env:AGENTLAB_WSL_INTEGRATION = '1'
python -m unittest discover -s tests -p test_repair_wsl.py -v
```

The tiny `examples/repair-demo` project is intentionally broken for a repair demonstration. Choose a test command that actually verifies your objective; passing an unrelated command cannot prove a repair.
