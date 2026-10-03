# AgentLens

A learning project: a small agent loop with explicit tools and JSONL traces.
Scripted demos make the mechanics visible. A first live adapter also supports
OpenRouter's `qwen/qwen3.7-flash`; the initial live exercise exposes only `read_file`
for `pyproject.toml`. The live Docker exercise uses all seven tools in a disposable repo.

## Additional concepts in our learning scope

**Event:** An immutable record of something that happened during execution.
Examples: `model_started`, `model_completed`, `tool_requested`, `tool_started`,
`tool_completed`, `checkpoint_created`, and `run_failed`. A request and the start
of execution are different events: a requested action may never execute.
Recorded events describe history; corrections should be new events, not rewrites.

`Event` in `src/agentlens/tracing.py` is a frozen dataclass: normal field
assignments are rejected. Each event contains a run ID, sequence number, UTC
timestamp, event name, and payload. The payload is stored as a JSON string because
freezing a dataclass alone would still allow edits inside a nested dictionary.
`event.data` decodes a fresh dictionary; changing that copy cannot alter the record.
`event.to_dict()` exports the existing trace format, with `data` as a JSON object.

`Trace.record(...)` creates an Event, appends it to the JSONL file, then returns it.
The loop's existing callers can ignore this return value. Event objects represent
individual facts; Trace manages their ordering and persistence. Read `tracing.py`,
then `tests/test_tracing.py` to follow this distinction.

The JSONL file itself can still be edited: immutable records are not tamper-proof
storage. Event names currently differ from the examples above. Checkpoints are
not implemented; the example name does not imply a checkpoint subsystem exists.

**Capability:** A scoped permission allowing an agent to perform an action against
a resource, subject to constraints. For example:

```yaml
agent: coding_agent_17
resource: repo/project-x
actions: [read, write]
constraints:
  branch: "!= main"
```

Tool availability is not authorization. A registered `apply_patch` function tells
the harness how to edit; it does not establish that this agent may edit this repo
on this branch. Authorization concerns the specific action and resource before
execution. A command tool can also write files, so an eventual check cannot rely
only on whether a dedicated editing tool is registered.

These are additions to our learning scope. We will work through them incrementally;
do not build a sophisticated policy system now. The example capability is not
currently enforced. Docker isolation and process permissions are the existing
execution boundaries, not an implementation of this capability model.

Remaining work includes basic capabilities, 5–10 repository-understanding tasks with graders,
and then the agent's first actual bug.

The cold test is unchanged: rebuild the core loop without looking at its
implementation. The artifact remains a primitive but understandable coding agent.

## Run locally

From the repository root, with the existing virtual environment:

```sh
.venv/bin/agentlens
```

## Run inside Docker

Prerequisite: Docker must be installed and its engine running. `docker version`
should show both client and server information.

Read `Dockerfile`, then `.dockerignore`, then the commands below. No Python loop
changes are required: the same harness and tools execute in a different environment.

Build the image (requires network access to download Python and the build backend):

```sh
docker build -t agentlens:learning .
```

Start the existing Python-version demo:

```sh
docker run --name agentlens-demo \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --memory 256m --cpus 1 --pids-limit 64 \
  agentlens:learning
```

The image is a prepared filesystem; the container is a running instance of it.
The command above runs as user `agent` (UID 10001), disables external networking,
drops Linux capabilities, and limits memory, CPU, and process count. It mounts no
host directories or Docker socket. The agent can write to its `/workspace` and
other locations permitted to that user, but those changes are inside the container.
This is process isolation, not a guarantee against every possible container escape.

Expect a trace path and a Python version result with exit code 0. The interpreter
path should be inside the container, rather than your Mac's `.venv`. Networking is
disabled for this scripted demo; a future API-backed model will need an explicit
network design.

The container stops when the demo finishes. Keep it long enough to retrieve traces:

```sh
mkdir -p traces
docker cp agentlens-demo:/workspace/traces traces/docker-demo
docker inspect --format '{{.State.ExitCode}}' agentlens-demo
```

Inspect the copied JSONL file for `model_request`, `model_response`, `tool_request`,
`tool_result`, and a final `run_end` with status `finished`.

After inspecting and copying anything you want to keep, remove the stopped
container before reusing its name:

```sh
docker rm agentlens-demo
```

Rebuild the image after changing source code; a previous image contains the old
snapshot. Each new container starts from that snapshot. The initial image installs
the application, pytest, and Git.

The Python-version container demo was verified on September 30, 2026: the container
exited with code 0 and its copied trace ended with `run_end`, status `finished`.

## First editing tool

Read `src/agentlens/tools.py` (`apply_patch`), then `src/agentlens/__init__.py`
(`scripted_patch_model` and `main`), then `tests/test_tools.py`.
Our patch format takes `path`, `old_text`, and `new_text`; it is exact text
replacement, not unified-diff syntax. Old text must be nonempty and occur exactly
once. Missing or ambiguous text raises an error before any write. This first
version edits existing UTF-8 files, with no concurrent-writer coordination.

```sh
.venv/bin/agentlens --demo patch
```

The executable is the installed agent in your virtual environment. `--demo patch`
selects the editing demonstration; omitting it retains the Python-version demo.
Setup creates a temporary greeting file. The scripted model requests a read, a
replacement, and a read-back. Expect `Hello, agent!` in the final answer. The
temporary file is removed afterward; the trace preserves the interactions.

To run the same demonstration inside Docker, rebuild with the build command above,
then run:

```sh
docker run --rm --network none --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --memory 256m --cpus 1 --pids-limit 64 \
  agentlens:learning agentlens --demo patch
```

`docker run` starts a container; `--rm` removes it and its internal trace after
exit. `--network none` disables external networking; `--cap-drop ALL` removes
optional Linux privileges; `--security-opt no-new-privileges=true` prevents gaining
privileges through executables. `--memory 256m`, `--cpus 1`, and `--pids-limit 64`
limit memory, CPU time, and processes/threads. `agentlens:learning` selects the
image; `agentlens --demo patch` overrides its default command to select this demo.
Each trailing backslash continues the command onto the next line. The interaction
history is printed in the terminal. To retain the container trace, omit `--rm`,
add a unique `--name`, and use `docker cp` as described above.

Reference: [Docker run documentation](https://docs.docker.com/engine/containers/run/).

## Running tests as a tool

`run_tests(cwd=".", timeout=30)` runs the current Python interpreter with
`-m pytest -q` in the chosen directory. `-m` runs pytest as a Python module;
`-q` reduces output verbosity. Pytest discovers tests in that directory.
The timeout is in seconds and uses the same process handling as `run_command`.
The result contains `stdout`, `stderr`, and `exit_code`: 0 means passing, 1 means
test failures, and 5 means no tests collected. Other nonzero codes also mean the
run did not pass. The harness's `ok: true` only means the tool returned a result.
This executes test code; it is not a scoped capability or authorization check.

```sh
.venv/bin/agentlens --demo tests
```

This runs the local executable with `--demo tests` selecting a disposable,
single-test suite. Expect `1 passed` and exit code 0. It checks the tool mechanics,
not an agent's bug-fixing ability. Setup creates the suite and removes it afterward.

For Docker, rebuild the image (pytest is now installed during the build), then use
the editing-demo Docker command above with `--demo tests` instead of `--demo patch`.
The network restriction still applies at runtime; pytest is already in the image.
This demo creates its own fixture; the project's development tests are not copied
into the image yet.

Read `tools.py` (`run_tests`), `__init__.py` (`scripted_test_model`), and
`tests/test_tools.py` (passing, failing, and empty suites).

## Inspecting edits with Git

`git_diff(cwd=".")` returns stdout, stderr, and exit_code from:

```sh
git --no-pager diff --no-ext-diff --no-textconv --no-color HEAD --
```

`git` invokes Git; `--no-pager` prints directly instead of opening a pager.
`diff` compares file versions. `HEAD` chooses the latest commit as the baseline,
so the result includes the net effect of staged and unstaged tracked changes.
`--no-ext-diff` and `--no-textconv` disable external diff helpers and text converters;
`--no-color` removes terminal color codes. The final `--` ends revision/options
arguments; no path filter follows, so the comparison covers the repository.
It excludes untracked files and requires at least one commit. Empty output means
no tracked changes only if the command succeeded. This tool does not stage or commit.

```sh
.venv/bin/agentlens --demo diff
```

The local executable's `--demo diff` selects a disposable Git repository exercise.
Setup writes a greeting and makes a baseline commit there. `git init --quiet`
initializes that temporary repository quietly; `git add greeting.txt` stages the
fixture; `git commit --quiet -m "Demo baseline"` records it with the message after
`-m`. Each `-c key=value` applies configuration for that command only: demo identity,
disabled commit signing, and disabled hooks. No global Git settings are changed.
Then the scripted model requests a patch and a diff. Expect `-Hello, world!` and
`+Hello, agent!`. The directory is removed afterward; the local JSONL trace remains.

Git is now installed during the Docker build: `apt-get update` refreshes package
metadata, and `apt-get install -y --no-install-recommends git` installs Git without
interactive confirmation (`-y`) or optional recommended packages. The build then
removes the downloaded package lists to reduce image size.
Rebuild the image, then use the documented Docker demo command with `--demo diff`.
The same isolation flags apply, and no runtime network access is needed.

## Live model: Qwen3.7 Flash through OpenRouter

Read `src/agentlens/models.py`, then the live branches of `main()` in
`src/agentlens/__init__.py`, then `tests/test_models.py`.

The adapter uses Python's standard HTTP library. It sends history and tool
schemas to `https://openrouter.ai/api/v1/chat/completions`, requesting
`qwen/qwen3.7-flash`, then converts the response into our loop's existing
`tool_call` or `final` shape. Provider messages and tool-call IDs are preserved.
Multiple tool calls and truncated responses raise errors. Streaming is disabled,
with a 4,096-token output limit per request and a 60-second socket timeout.
The small `live` demo permits four model turns; `live-docker` permits sixteen.

This replaces the free OpenRouter model. Qwen3.7 Flash is **paid**: OpenRouter lists
$0.03 per million input tokens and $0.13 per million output tokens as checked
October 3, 2026. Credit purchase fees may apply separately. Create an
[OpenRouter key](https://openrouter.ai/settings/keys) and fund that account.
Your old OpenRouter key will not work here.

In zsh:

```sh
read -rs 'OPENROUTER_API_KEY?OpenRouter API key: '
export OPENROUTER_API_KEY
```

`read` prompts for input; `-r` preserves backslashes and `-s` hides input.
Zsh's `NAME?prompt` syntax stores the answer in `OPENROUTER_API_KEY`.
Paste the key at the prompt and press Enter. `export` passes it to programs
started from that terminal. Keep the key out of source files and chat.
The adapter does not load `.env` files. Exporting in your terminal does not
update an already-running assistant process's environment.

```sh
.venv/bin/agentlens --demo live
```

This runs the project's installed executable. `--demo` selects an exercise;
`live` asks the model to read `pyproject.toml` for the package name, Python
requirement, and CLI entry point. The only executable tool permits that file.
Its contents are sent to OpenRouter as feedback.

Traces contain request bodies, responses, usage metadata and tool events,
but never Authorization headers. Offline tests mock HTTP responses and do not
prove live access works for your account.

HTTP 408, 429, 502 and 503 failures are retried at most twice, waiting 10 then
20 seconds. Retry-After can increase that delay; a delay above 60 seconds stops
the run. Authentication and credit errors are not retried. Connection/read
timeouts share the three-attempt budget; other URL errors are not retried.
Only numeric provider codes and fixed error explanations are logged, not raw
error bodies. An error inside an HTTP 200 response stops the run safely.
The socket timeout is not a strict total response deadline. Retried model
requests may incur charges, but completed tool actions are not replayed.
Rerunning the Docker demo creates a new disposable repository.

The model calls run on the host, so this provider switch does not require
rebuilding the Docker image. The key stays on the host; tools run inside Docker.

Sources: [model and pricing](https://openrouter.ai/qwen/qwen3.7-flash),
[API quickstart](https://openrouter.ai/docs/quickstart),
[error handling](https://openrouter.ai/docs/api/reference/errors-and-debugging).

## Live model with Docker tools

Read `docker_tools.py`, `tool_schemas.py`, `models.py`, the `live-docker` branch
in `__init__.py`, then `tests/test_docker_tools.py`.

The host owns the loop, trace, and OpenRouter key. The model sees seven tool descriptions,
while the host's registry maps those names to Docker bridge functions. Each bridge
call sends JSON on standard input to `python -m agentlens.docker_tools worker`
inside the container. The worker runs the existing tool and returns JSON. `-m`
executes a Python module; `worker` selects its request-handling branch. This is
ordinary process communication, not another agent framework.

Rebuild once after these source changes:

```sh
docker build -t agentlens:learning .
```

`build` creates the image, `-t agentlens:learning` names and tags it, and `.` supplies
this directory as build context. Then, in the terminal where you exported your key:

```sh
.venv/bin/agentlens --demo live-docker
```

The local executable's `--demo live-docker` selects host-side model calls with
container-side tools. It starts a uniquely named container, prepares a small Git
repository, and asks Qwen to inspect files, edit a greeting, search Python code,
check Python's version, run tests, and inspect the diff. This is an integration
exercise, not the first actual bug task or the repository-understanding eval suite.
It permits up to 16 model calls; model output can vary. All tool results are sent
back to OpenRouter. The host independently reads the greeting and reruns tests and diff
after the answer, recording a `verification` event. These checks are evidence to
inspect, not a tamper-resistant grader: the agent can edit tests in this fixture.

The bridge starts Docker with `--detach` (background), `--name` (unique identifier),
`--network none` (no external networking), `--read-only` (immutable image filesystem),
`--cap-drop ALL` (remove optional Linux privileges), and
`--security-opt no-new-privileges=true` (prevent privilege gain through executables).
`--memory 512m`, `--cpus 1`, and `--pids-limit 64` limit resources.
`--tmpfs` creates size-limited writable memory-backed directories: `/repo` belongs
to the non-root agent user; `/tmp` provides scratch space. No host directories,
Docker socket, or API-key variables are mounted or forwarded. Docker's own host
client inherits the host environment, but the container does not inherit it.

For each call, `docker exec --interactive --workdir /repo` starts a worker in the
existing container. `--interactive` keeps stdin open for JSON; `--workdir` sets
the working directory. Model arguments travel as JSON, not shell command text.
The container's idle process has a 30-minute lifetime. On normal exit or a Python
exception, `docker rm --force` removes only this run's uniquely named container.
An abrupt host kill can leave a stopped container requiring manual cleanup.
Temporary repository changes disappear; traces remain on the host.

The opt-in integration test exercises all seven tools and checks that the API key
is absent, the user is non-root, and writes to the image filesystem fail:

```sh
AGENTLENS_DOCKER_TEST=1 .venv/bin/python -m pytest -q tests/test_docker_tools.py
```

The leading assignment enables Docker tests only for this command; `-m pytest`
runs pytest using the virtual environment's Python, `-q` reduces verbosity, and
the final path selects the test file. It requires a built image and running engine.
