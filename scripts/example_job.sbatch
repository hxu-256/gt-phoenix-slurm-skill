#!/bin/bash
# =============================================================================
# GT PACE Phoenix - annotated reference sbatch script
# =============================================================================
# This file is a WORKING, VERIFIED template. Copy it and edit the marked lines.
#
# Preferred way to create a job script is a heredoc ON THE LOGIN NODE, which
# guarantees Unix (LF) line endings:
#
#   ssh <remote_host> "cat > /path/to/job.sbatch <<'EOF'
#   ...script body...
#   EOF"
#
# Use a QUOTED heredoc delimiter ('EOF', not EOF) so that $SLURM_JOB_ID,
# $HOME, $(hostname) etc. are written literally instead of being expanded by
# your local shell before they ever reach the cluster.
#
# !! NEVER create .sbatch files on Windows and scp them across without
# !! converting line endings. CRLF makes bash fail with confusing
# !! "$'\r': command not found" errors on the compute node. Check with
# !! `file job.sbatch`; fix with `sed -i 's/\r$//' job.sbatch`.
# =============================================================================

#SBATCH --job-name=my_job                 # <-- EDIT: shows up in squeue
#SBATCH --account=gts-<pi_username>       # <-- EDIT: REQUIRED, job is rejected without it
                                          #     Find yours with: pace-quota
                                          #     (it is the "Job Charge Account" name)

# -----------------------------------------------------------------------------
# QOS: pick ONE. This is a cost-vs-reliability decision, make it deliberately.
# -----------------------------------------------------------------------------
#   inferno  UsageFactor 1.0  -> CHARGES your allocation hours.
#            Priority 250000. Preempts embers jobs. Walltime up to the
#            partition maximum (3 days on GPU partitions, 21 days on CPU).
#            This is the DEFAULT QOS if you write no -q line at all.
#            Use for: real runs, anything you cannot afford to lose.
#
#   embers   UsageFactor 0.0  -> FREE, consumes no allocation hours.
#            Priority 0, and it is PREEMPTIBLE: an inferno job needing the
#            node will evict you (1 hour grace period). Hard 8 hour walltime cap.
#            Use for: cheap experiments, and ONLY with checkpoint/resume,
#            because you must assume the job will be killed partway through.
#
#SBATCH --qos=inferno                     # <-- EDIT: inferno (paid) | embers (free, preemptible)

# -----------------------------------------------------------------------------
# PARTITION + HARDWARE: choose before firing. Asking for more than a partition
# physically has means your job pends forever instead of failing fast.
# Verify current values with:  sinfo -p <partition> -o '%G %c %m %l'
# -----------------------------------------------------------------------------
#  Partition   | GPUs/node        | Cores/node | RAM/node   | Max walltime
#  ------------|------------------|------------|------------|-------------
#  gpu-v100    | 2x V100 (16 GB)  | 24         | ~191 GB    | 3 days
#  gpu-a100    | 2x or 8x A100    | 64         | 515/2051GB | 3 days
#  gpu-h100    | 8x H100          | 64-112     | ~2063 GB   | 3 days
#  gpu-h200    | 8x H200          | 64         | ~2063 GB   | 3 days
#  cpu-small   | none             | 24+        | ~191 GB    | 21 days
#  cpu-large   | none             | 24+        | ~772 GB    | 21 days
#  cpu-amd     | none             | 128        | ~3095 GB   | 21 days
#  cpu-gnr     | none             | 192        | ~1547 GB   | 21 days
#
#  Run `pace-hardware` for exact GPU VRAM per model.
#
#  How to choose:
#   - Small/medium model, or you are just testing? gpu-v100. It is the largest
#     GPU partition, so it has the shortest queue. Do not burn H100 hours on MNIST.
#   - Model does not fit in 16 GB, or you need bf16/flash-attention? gpu-a100+.
#   - No GPU code at all? Use a cpu-* partition. Requesting an idle GPU wastes
#     allocation hours and delays other users.
#
#SBATCH --partition=gpu-v100              # <-- EDIT
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1                      # <-- EDIT: drop this line entirely for CPU-only jobs.
                                          #     Optionally pin a model: --gres=gpu:V100:1

# -----------------------------------------------------------------------------
# CPU / MEMORY: request what you use, not the whole node.
# -----------------------------------------------------------------------------
#  - cpus-per-task mainly feeds DataLoader workers. A good starting point is
#    4-8 per GPU. Do NOT request cores/GPU beyond the node ratio
#    (v100: 24 cores / 2 GPUs = 12 max per GPU; h100: 64 / 8 = 8 per GPU),
#    or Slurm must wait for a whole idle node and you sit in PENDING.
#  - Over-requesting memory has the same effect. Right-size using the MaxRSS
#    column from a previous run: sacct -j <jobid> --format=JobID,MaxRSS,Elapsed
#
#SBATCH --cpus-per-task=4                 # <-- EDIT
#SBATCH --mem=16G                         # <-- EDIT
#SBATCH --time=01:00:00                   # <-- EDIT: HH:MM:SS. Job is KILLED at this limit.
                                          #     Too long also hurts: it delays backfill scheduling.
                                          #     Remember embers caps at 08:00:00.

#SBATCH --output=python_run_%j.out        # %j expands to the job ID
#SBATCH --error=python_run_%j.err
# Optional email on completion/failure:
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=you@gatech.edu

# =============================================================================
# Job body
# =============================================================================

# Land in the directory you submitted from, not $HOME.
cd "$SLURM_SUBMIT_DIR" || exit 1

# Keep heavy I/O and outputs on scratch, never in $HOME (small quota, and a
# full home breaks logins). Resolve your own scratch with: readlink -f ~/scratch
echo "Job $SLURM_JOB_ID on $(hostname) starting at $(date)"
echo "Working directory: $(pwd)"

# Call the conda environment's python binary DIRECTLY.
# Do not use `module load anaconda3` / `conda activate` / `conda run` here:
# module loading is inconsistent across compute nodes and mangles $PATH.
PYTHON="$HOME/.conda/envs/<env_name>/bin/python"   # <-- EDIT env name

"$PYTHON" my_script.py --data-dir ./data --out-dir ./results   # <-- EDIT

# -----------------------------------------------------------------------------
# Capture the exit code IMMEDIATELY, on its own line.
#
# Do NOT write:  echo "finished at $(date) with code $?"
# The $(date) command substitution runs first and overwrites $?, so that line
# always reports 0. Worse, if the script's last command is a successful echo,
# the script exits 0 and Slurm records the job as COMPLETED even though your
# training crashed. The explicit `exit $rc` below is what makes a real failure
# show up as FAILED in sacct.
# -----------------------------------------------------------------------------
rc=$?
echo "Job $SLURM_JOB_ID finished at $(date) with exit code $rc"
exit $rc
