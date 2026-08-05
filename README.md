# gatech-phoenix-slurm

An agent skill for running jobs on the Georgia Tech
**PACE Phoenix** Slurm cluster — submitting batch jobs, checking quotas and queues, and
reading back logs, without writing raw Slurm syntax by hand.

---

## Prerequisites

Three things must be true before the skill can do anything. None are scriptable:

1. You have a GT account with PACE access.
2. Your PI has added you to their allocation.
3. SSH to a Phoenix login node works **without an interactive prompt** (see below).

---

## One-time SSH setup

### 1. Generate a key and install it

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_pace -C "gtusername@gatech.edu"

# push the public key (portable; ssh-copy-id is often missing on Windows)
cat ~/.ssh/id_ed25519_pace.pub | ssh gtusername@login-phoenix.pace.gatech.edu \
  "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
```

This is the only time you use your GT password — expect a **Duo 2FA prompt**. If the
connection times out instead of prompting, you likely need the GT VPN (GlobalProtect).

### 2. Add an alias to `~/.ssh/config`

On Windows this is `C:\Users\<you>\.ssh\config`.

```sshconfig
Host pace-login
  HostName login-phoenix.pace.gatech.edu
  User gtusername
  IdentityFile ~/.ssh/id_ed25519_pace
  ServerAliveInterval 60
```

### 3. Verify it is passwordless — do not skip this

```bash
ssh -o BatchMode=yes pace-login "whoami"
```

`BatchMode=yes` disables all interactive prompts, so this must print your username.

> **This is a hard requirement, not a convenience.** The agent cannot answer a password or
> Duo prompt. If key authentication is not working, every command it runs will hang until it
> times out.

---

## Install in Claude as an example

```bash
git clone git@github.com:<org>/gt-phoenix-slurm-skill.git \
  ~/.claude/skills/gatech-phoenix-slurm
```

Update later with:

```bash
git -C ~/.claude/skills/gatech-phoenix-slurm pull
```

---

## First run

Just describe what you want — no special syntax:

> "set up the phoenix skill for my account, ssh host is pace-login"

The agent finds no config and determines your settings from the cluster:

```bash
ssh pace-login "whoami"                                             # -> gt_username
ssh pace-login "sacctmgr -n show assoc user=<u> format=Account%25"  # -> pi_account
ssh pace-login "readlink -f ~/scratch"                              # -> remote_workdir
```

It only needs to ask you something if `sacctmgr` returns more than one PI allocation.


---

## Configuration

Lives at `~/.phoenix_agent_config.json` on your **local** machine per-user.
```json
{
  "gt_username": "jsmith30",
  "pi_account": "gts-jsmith30",
  "default_partition": "gpu-v100",
  "remote_host": "pace-login",
  "remote_workdir": "/storage/scratch1/<shard>/<user>"
}
```

`remote_host` is whatever reaches the login node — an SSH alias (preferred) or
`<user>@login-phoenix.pace.gatech.edu`.

---

## Verify your setup (recommended first job)

`examples/mnist_test.py` proves the whole chain works — conda env, GPU visibility, scratch
I/O, sbatch submission, log retrieval. Just ask:

> "run the mnist setup test on phoenix using my torch conda environment"

**Expected:** `State=COMPLETED`, `ExitCode=0:0`, and roughly **99% validation accuracy** in
well under a minute on a single V100.

The script also reports peak VRAM and peak host RAM, so the same run doubles as a probe for
sizing real jobs — request the measured peak x 1.3-1.5 rather than guessing.

---

## Typical use

> "run train.py on phoenix with the DDPM env, 3 epochs"

The skill will stage code to scratch, syntax-check on the login node, run a short smoke job,
then submit the full job and summarize the logs.

---

## What's in here

| Path | Purpose |
| :--- | :--- |
| `SKILL.md` | The skill itself — workflow, gotchas, QOS reference |
| `references/gt_phoenix_guide.md` | Phoenix quick reference: partitions, hardware, storage, commands |
| `scripts/example_job.sbatch` | Annotated, working sbatch template — the single source of truth |
| `examples/mnist_test.py` | Setup-verification job; also reports peak VRAM/RAM for sizing real jobs |
| `.gitattributes` | Forces LF line endings (see below) |

---

## Notes for contributors

- **Never let a `.sbatch` acquire CRLF.** Git for Windows defaults to `core.autocrlf=true`,
  which rewrites LF to CRLF on checkout; a CRLF job script dies on the compute node with
  `$'\r': command not found`. The `.gitattributes` in this repo prevents that — do not
  remove it. Verify with `git ls-files --eol` or `file scripts/example_job.sbatch`.
- **Keep user-specific values out.** No usernames, no account names, no absolute scratch
  paths. Those belong in each user's local config. Placeholders only.
- **Verify cluster facts before documenting them.** Quotas, partitions, and QOS policy change.
  The hardware and QOS tables are point-in-time snapshots and say so; confirm with
  `sinfo -p <partition> -o '%G %c %m %l'`, `sacctmgr show qos`, and `pace-quota` rather than
  trusting anything written here.
- **Capture exit codes correctly.** `echo "done $(date) code $?"` always reports 0, because
  the command substitution overwrites `$?`. Use `rc=$?` on its own line, and end scripts with
  `exit $rc` — otherwise a trailing successful `echo` makes Slurm record a crashed job as
  COMPLETED.
