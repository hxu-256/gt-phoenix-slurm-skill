# Georgia Tech PACE Phoenix Cluster Quick Reference

> Figures below were verified against the live cluster. Quotas and hardware change over
> time — treat `pace-quota`, `sinfo`, `sacctmgr`, and `pace-hardware` as authoritative
> and re-check rather than trusting any number written here.

## Cluster Overview & Connection
- **Login node:** `login-phoenix-slurm.pace.gatech.edu` (an SSH alias in `~/.ssh/config`, e.g. `pace-login`, is preferred — use whatever `remote_host` in the config specifies)
- **Scheduler:** Slurm Workload Manager
- **Web Portal:** PACE Open OnDemand — <https://ondemand-phoenix.pace.gatech.edu>

## Account Directive Syntax
Every `#SBATCH` submission script **must** specify an active GT allocation account:
```bash
#SBATCH --account=gts-<pi_username>
```
The account name frequently differs from the PI's bare surname — it commonly carries a first
initial and/or a trailing digit, so a PI named "Jane Smith" may map to `gts-jsmith30` rather
than `gts-smith`. Confirm the exact string before submitting:
```bash
pace-quota                                                  # 'Job Charge Account Balances'
sacctmgr -n show assoc user=<username> format=Account%25,QOS%20
```

## QOS: inferno vs embers
```bash
sacctmgr -n show qos format=Name,Priority,UsageFactor,Preempt,MaxWall
```
| QOS | UsageFactor | Priority | Preemption | Max walltime |
| :--- | :--- | :--- | :--- | :--- |
| `inferno` (default) | **1.0 — charges hours** | 250000 | preempts `embers` | partition max |
| `embers` | **0.0 — free** | 0 | **preempted by `inferno`**, 1 h grace | **8 h** |

`embers` costs nothing but can be evicted at any time and is capped at 8 hours — only use it
for work that checkpoints and can resume.

## Direct Python Environment Execution (Best Practice)
Rather than loading modules (`module load anaconda3`) or using `conda activate` / `conda run`,
which are inconsistent across compute nodes and cause `$PATH` conflicts, execute the
environment's Python binary directly:
```bash
cd "$SLURM_SUBMIT_DIR"
$HOME/.conda/envs/<env_name>/bin/python <script.py>
```

## Reliable exit-code reporting
```bash
$HOME/.conda/envs/<env>/bin/python train.py
rc=$?                                     # capture IMMEDIATELY, on its own line
echo "finished at $(date) with code $rc"
exit $rc                                  # without this, Slurm reports COMPLETED on crash
```
Never write `echo "... $(date) ... $?"` — the command substitution runs first and overwrites
`$?`, so the line always prints 0.

## Complete GT PACE Specific Commands
- `pace-quota`: Storage utilization (Home, Scratch, Project) and charge account balances.
- `pace-whoami`: User account details and associated GT PI charge allocations.
- `pace-check-queue [queuename]`: Node status, core/RAM utilization, and queue wait conditions.
- `pace-hardware`: Node hardware specs, CPU models, and GPU types/VRAM across PACE clusters.

## Hardware & Resource Requests
Verify with `sinfo -p <partition> -o '%G %c %m %l'` before submitting.

| Partition | GPUs/node | Cores/node | RAM/node | Max walltime |
| :--- | :--- | :--- | :--- | :--- |
| `gpu-v100` | 2x V100 (16 GB) | 24 | ~191 GB | 3 days |
| `gpu-a100` | 2x or 8x A100 | 64 | 515 / 2051 GB | 3 days |
| `gpu-h100` | 8x H100 | 64-112 | ~2063 GB | 3 days |
| `gpu-h200` | 8x H200 | 64 | ~2063 GB | 3 days |
| `cpu-small` | none | 24+ | ~191 GB | 21 days |
| `cpu-large` | none | 24+ | ~772 GB | 21 days |
| `cpu-amd` | none | 128 | ~3095 GB | 21 days |
| `cpu-gnr` | none | 192 | ~1547 GB | 21 days |

| Request | SBATCH Directive |
| :--- | :--- |
| CPU cores | `#SBATCH --cpus-per-task=4` |
| Memory | `#SBATCH --mem=32G` |
| One GPU | `#SBATCH --gres=gpu:1` (or pin a model: `--gres=gpu:V100:1`) |
| Walltime | `#SBATCH --time=04:00:00` |
| QOS | `#SBATCH --qos=inferno` (or `embers`) |

**Selection guidance:** `gpu-v100` is the largest GPU partition and therefore usually the
shortest queue — prefer it for testing and for models that fit in 16 GB. Move to `gpu-a100`
or above only when VRAM or bf16/flash-attention demands it. Request 4-8 CPUs per GPU; going
beyond the node's core-to-GPU ratio (v100: 12, h100: 8) forces Slurm to wait for a whole idle
node. Omit `--gres` entirely for CPU-only work.

## Standard Storage Paths
- **Home:** `/storage/home/hcoda1/<shard>/<user>` — small quota, for code and scripts. A full home breaks logins.
- **Scratch:** `/storage/scratch1/<shard>/<user>` — high-speed, large datasets, temporary outputs.
- **Project:** `/storage/project/<group>` — shared group storage.

`<shard>` is a per-user digit, **not** a group name, and scratch has **no** `hcoda1` component.
Do not hardcode these: resolve with `readlink -f ~/scratch`, or simply use the `~/scratch` symlink.
Check current limits with `pace-quota`.

## Line endings (Windows users)
A `.sbatch` written on Windows and copied over carries CRLF and fails on the compute node with
`$'\r': command not found`. Create job scripts on the login node with a quoted heredoc
(`ssh <host> "cat > job.sbatch <<'EOF' ... EOF"`), or repair after copying:
```bash
file job.sbatch                 # must NOT say "with CRLF line terminators"
sed -i 's/\r$//' job.sbatch
bash -n job.sbatch              # shell syntax check
```

## Useful Slurm & PACE Commands
- `sbatch job.sbatch`: Submit a job script.
- `squeue -u <username> -o '%.10i %.12j %.9P %.8T %.10M %R'`: Job status with pending reason.
- `sacct -j <job_id> --format=JobID,JobName,State,Elapsed,ExitCode,MaxRSS,NodeList`: History, exit codes, peak memory.
- `scancel <job_id>`: Cancel a pending or running job.
- `srun --account=gts-<pi> --partition=<queue> --gres=gpu:1 --time=00:30:00 --pty bash`: Interactive session on a compute node.
- `sinfo -p <partition> -o '%G %c %m %l'`: What a partition actually offers.

**Slurm state codes:** `PD` Queued · `R` Running · `CD` Completed · `F` Failed ·
`PR` Preempted (embers) · `TO` Timed out · `OOM` Out of memory · `CA` Cancelled.
