---
name: gatech-phoenix-slurm
description: "Inspect, submit, monitor, and manage compute jobs on the Georgia Tech PACE Phoenix Slurm cluster without needing raw Slurm syntax. Auto-configures GT PI account settings, checks PACE quotas (`pace-quota`), inspects GT queue states (`pace-check-queue`), and generates valid sbatch scripts with pre-flight validation. Use when the user wants to run experiments, submit batch jobs, check PACE quota/balances/queues, or view slurm logs on GT Phoenix."
---
# gatech-phoenix-slurm

An agent skill to interface with Georgia Tech's Partnership for an Advanced Computing Environment (PACE) Phoenix Slurm cluster. Abstracts Slurm directives (`sbatch`, `squeue`, `sacct`, `scancel`) and GT PACE utilities (`pace-quota`, `pace-whoami`, `pace-check-queue`, `pace-hardware`), managing user-specific PACE configuration (`gts-<pi_username>`).

This skill requires **no local Python and no helper scripts**. Job scripts are created on the login node with a heredoc, which is portable and guarantees correct line endings. `scripts/example_job.sbatch` is the single annotated source of truth for the script format.

## When to Use

Use this skill when the user asks to:
- Run a Python script, machine learning experiment, or computational batch job on GT Phoenix.
- Perform pre-flight code validation (syntax check, Conda environment check, GPU dry-run) before job launch.
- Check GT PACE storage usage, remaining project allocations, or charge account balances using `pace-quota`.
- Check human-readable GT PACE queue status, node availability, or queue wait reasons using `pace-check-queue`.
- Generate or validate a Slurm (`.sbatch`) submission script tailored for PACE Phoenix hardware.
- Check job queue status (`squeue`), resource allocations, or history (`sacct`) on Phoenix.
- Retrieve and summarize job stdout/stderr log files (`python_run_<job_id>.out` or `slurm-<job_id>.out`).
- Configure or update local GT username and PI allocation account settings.

## Core Workflow

### Step 1: Configuration & Allocation Management

Configuration lives in `~/.phoenix_agent_config.json` on the **local** machine. Read and write it directly with the Read and Write tools — do not shell out, and do not pass POSIX paths as shell arguments (see Gotchas: MSYS path mangling).

```json
{
  "gt_username": "jsmith30",
  "pi_account": "gts-jsmith30",
  "default_partition": "gpu-v100",
  "remote_host": "pace-login",
  "remote_workdir": "/storage/scratch1/<shard>/<user>"
}
```

- `remote_host` is whatever reaches the login node: an SSH alias from `~/.ssh/config` (preferred, e.g. `pace-login`) or `<user>@login-phoenix-slurm.pace.gatech.edu`. **Always use the configured value**; never hardcode a host in commands.
- `pi_account` must carry the `gts-` prefix. Add it if the user omits it.

If `gt_username` or `pi_account` is missing, prompt the user once:
> "To submit jobs to GT Phoenix, please provide your GT Username and PI Account ID (e.g., `gts-jsmith30`)."

**Verify the account rather than trusting it.** The charge account name often differs from the PI's plain surname — it commonly carries a first initial and/or a trailing digit, so a PI named "Jane Smith" may map to `gts-jsmith30` rather than `gts-smith`. A wrong account is rejected at submission. Confirm with either:
```bash
ssh <remote_host> "pace-quota"                                    # 'Job Charge Account Balances' section
ssh <remote_host> "sacctmgr -n show assoc user=<gt_username> format=Account%25,QOS%20"
```

Other checks:
```bash
ssh <remote_host> "pace-quota"                          # storage + allocation balance
ssh <remote_host> "pace-check-queue <partition>"        # queue health
ssh <remote_host> "readlink -f ~/scratch"               # resolve the real scratch path
```

### Step 2: Pre-Flight Code & Environment Validation

Run these on the **login node** before submitting. They are cheap and catch most failures.

1. **Python syntax:**
   `ssh <remote_host> "cd <workdir> && \$HOME/.conda/envs/<env>/bin/python -m py_compile <script.py>"`
2. **Shell syntax + line endings** of the job script:
   `ssh <remote_host> "cd <workdir> && file job.sbatch && bash -n job.sbatch"`
   `file` must **not** say "with CRLF line terminators".
3. **Environment & CUDA:**
   `ssh <remote_host> "\$HOME/.conda/envs/<env>/bin/python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'"`
   `cuda.is_available()` is **False on login nodes** — they have no GPU. That is expected and not a failure; only a compute node can confirm CUDA.
4. **Stage data on the login node.** If a dataset needs downloading, fetch it on the login node into scratch first (light I/O is fine) so the GPU job never depends on outbound network.
5. **Micro dry-run** on a real compute node, either a short `sbatch` (preferred — non-blocking, and produces a log) or:
   `srun --account=gts-<pi> --partition=<partition> --gres=gpu:1 --time=00:05:00 <cmd>`

### Step 3: Job Script Creation (heredoc on the login node)

Read `scripts/example_job.sbatch` for the annotated template, resource-selection guidance, and QOS semantics. Adapt it, then write it **on the login node** with a heredoc:

```bash
ssh <remote_host> "cat > <workdir>/job.sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=my_job
#SBATCH --account=gts-<pi>
...
EOF"
```

Use a **quoted** delimiter (`<<'EOF'`) so `$SLURM_JOB_ID`, `$HOME`, and `$(hostname)` are written literally instead of being expanded by the local shell first.

Choose resources deliberately before submitting — partition, QOS, GPU count, CPUs, memory, walltime. See the tables in `scripts/example_job.sbatch`. Review the script with the user before submitting.

### Step 4: Remote Execution & Submission

1. Copy code to scratch via `scp`/`rsync`.
2. **If any `.sbatch` was created locally and copied over**, normalize line endings first:
   `ssh <remote_host> "cd <workdir> && sed -i 's/\r$//' *.sbatch"`
3. `ssh <remote_host> "cd <workdir> && sbatch job.sbatch"`
4. Return the Job ID to the user.

### Step 5: Job Monitoring & Log Retrieval

1. `squeue -u <gt_username> -o '%.10i %.12j %.9P %.8T %.10M %R'` or `sacct -j <job_id> --format=JobID,JobName,State,Elapsed,ExitCode,MaxRSS,NodeList`
2. Translate state codes: `PD` → Queued, `R` → Running, `CD` → Completed, `F` → Failed, `PR` → Preempted (embers), `TO` → Timed out, `OOM` → Out of memory.
3. Poll in the background rather than blocking; report the queue reason (e.g. `(Priority)`, `(Resources)`) while pending.
4. On completion fetch `python_run_<job_id>.out` / `.err` and summarize. **Always check `.err` and the `sacct` ExitCode**, not just stdout.
5. Use `MaxRSS` from `sacct` to right-size memory on the next run.

## Complete GT PACE Specific Commands Reference

- `pace-quota`: Storage usage across Home, Scratch, and Project directories, plus charge account balances. Quotas change over time — read the live output, do not assume figures.
- `pace-whoami`: Active GT account, PI allocations, privileges (merged into `pace-quota`).
- `pace-check-queue [queuename]`: Human-readable queue status, nodes accepting vs blocked, per-node CPU/memory usage, bottlenecks.
- `pace-hardware`: Node hardware specs, CPU architectures, GPU models and VRAM across PACE clusters.

## QOS: cost vs. reliability

Phoenix defines two QOS levels. This choice is as important as the partition. Verify current values with
`sacctmgr -n show qos format=Name,Priority,UsageFactor,Preempt,MaxWall`.

| QOS | UsageFactor | Priority | Preemption | Max walltime |
| :--- | :--- | :--- | :--- | :--- |
| `inferno` | **1.0 — charges allocation hours** | 250000 | preempts `embers` | partition max (3 d GPU, 21 d CPU) |
| `embers` | **0.0 — free, no charge** | 0 | **preempted by `inferno`** (1 h grace) | **8 h** |

- `inferno` is the **default** when no `--qos` is given. Use it for real runs.
- `embers` is free but must be treated as disposable: recommend it only when the job checkpoints and can resume, and never for runs over 8 hours.

## Gotchas & Constraints

- **PI Allocation Requirement:** Jobs are rejected without a valid `#SBATCH --account=gts-<pi_username>`. Verify the exact name via `pace-quota`; it is often not the PI's bare surname.
- **CRLF line endings:** A `.sbatch` authored on Windows and copied over fails on the compute node with `$'\r': command not found`. Prefer heredoc-on-login-node; otherwise run `sed -i 's/\r$//'` and confirm with `file`.
- **Never build `$?` into an interpolated string:** `echo "done at $(date), code $?"` always reports 0, because the `$(date)` substitution runs first and overwrites `$?`. Capture `rc=$?` on its own line immediately after the command.
- **End job scripts with `exit $rc`:** without it, a trailing successful `echo` sets the script's status to 0 and **Slurm records a crashed job as COMPLETED**.
- **Direct Conda Binary Execution:** Do not rely on `module load`, `conda activate`, or `conda run` — module loading is inconsistent across nodes and mangles `$PATH`. Invoke `$HOME/.conda/envs/<env>/bin/python` directly.
- **Working Directory:** Always `cd $SLURM_SUBMIT_DIR` in the script, or the job runs in `$HOME`.
- **Login Node Resource Limits:** Never run training on login nodes. Syntax checks, small downloads, and file staging are fine; heavy compute is not.
- **Scratch Space Usage:** Send heavy I/O and large outputs to scratch, not `$HOME` (small quota; a full home breaks logins). **Do not hardcode the scratch path** — the layout is `/storage/scratch1/<shard>/<user>` where the shard is a per-user digit, not a group name. Resolve it with `readlink -f ~/scratch`, or just use the `~/scratch` symlink.
- **MSYS path mangling (Windows + Git Bash):** Passing a POSIX path such as `/storage/scratch1/...` as an argument to a native Windows binary makes Git Bash silently rewrite it to `C:/Program Files/Git/storage/...`. Avoid passing cluster paths as local shell arguments; keep them inside quoted remote commands, or prefix with `MSYS_NO_PATHCONV=1`.
- **Over-requesting resources causes PENDING, not failure:** asking for more CPUs, memory, or GPUs than a node in the partition has means the job waits indefinitely. Check against `sinfo -p <partition> -o '%G %c %m %l'`.
