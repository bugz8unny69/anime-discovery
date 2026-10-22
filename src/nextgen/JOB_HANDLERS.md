# Job handler module naming

A Python module that provides a job handler called by the worker MUST use a
lowercase snake_case name ending in `_job.py`. Use an action-oriented stem so
its purpose is clear when browsing the filesystem.

Examples of future module names:

| Purpose | Handler module | Offline test module |
| --- | --- | --- |
| Identify an anime | `identify_anime_job.py` | `test_identify_anime_job.py` |
| Acquire a release | `acquire_release_job.py` | `test_acquire_release_job.py` |

These are naming examples, not implemented handlers or authorization to build
provider/acquisition integrations. The eventual handler package location and
callable input/outcome contract will be settled with the worker implementation.

The suffix identifies the worker-facing handler entry module. Shared provider,
storage, configuration, throttling and other helper libraries keep descriptive
ordinary module names; calling a helper from a job does not make it a job handler.
The long-running worker process/module itself is named `worker`, without the
job suffix. A `_job.py` file is an importable module, not necessarily a standalone
CLI script or a separate process.

Job kinds are stable explicit registry keys. The worker maps each registered
kind to its handler callable; it must not derive imports from filenames supplied
in a job payload or scan and execute every file ending in `_job.py`. Renaming a
file alone does not rename persisted job kinds. Registry/async handler behavior
remains future implementation work.
