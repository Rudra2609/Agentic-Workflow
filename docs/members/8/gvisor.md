# Stronger isolation: gVisor and Firecracker (Sprint 8 stretch, evaluation write-up)

The Docker sandbox shares the host kernel (here: the Colima Linux VM's kernel). Containers stop accidents and casual
abuse (8/8 attack cases, [threat model](threat-model.md)), not a kernel exploit. Two ways to go further:

| | Docker (runc), today | gVisor (`runsc`) | Firecracker micro-VM |
|---|---|---|---|
| What runs the program's system calls | the shared Linux kernel, filtered by seccomp | **Sentry**, a kernel written in Go in user space; only a small set of host syscalls is used | a separate guest kernel in a KVM micro-VM |
| Kernel exploit escapes to | the VM's kernel | Sentry first (Go, memory-safe), then a much smaller host surface | the guest only; then the KVM hypervisor |
| Needs | Docker | Docker + the `runsc` binary as a Docker runtime; works without KVM (`systrap` platform) | **KVM** (`/dev/kvm`), a Linux host |
| Start-up | 0.093 s (measured on Colima) | 0.106 s measured here (published figures of 0.3–0.5 s are for older platforms) | ~0.125 s VM boot (Agache et al., NSDI 2020) + a root filesystem per run |
| Cost while running | none | syscall-heavy work 2–10× slower; pure computation ~unchanged (Young et al. 2019) | small CPU cost; memory per VM |
| Fits this laptop | yes | **yes, installed and measured below** (arm64, no KVM needed) | **no**: Colima's VM has no `/dev/kvm` (checked 2026-10-31: `ls /dev/kvm` → no such file); Apple Silicon offers no KVM to a nested Linux VM here |

## What is built
- `HMAP_TESTING_RUNTIME=runsc` makes every sandbox run use `docker run --runtime runsc …` (no network, read-only,
  non-root, no capabilities stay). Unset (default) = runc. If `runsc` is not installed, Docker refuses the run and the
  report shows an ENV failure: nothing falls back silently to weaker isolation.
- **Limits are layered differently under gVisor** (found while testing it). Under runc the container's cgroup limits
  stop the program itself: the kernel's OOM killer picks the memory hog, `fork` fails at `--pids-limit 64`. Under
  gVisor the cgroup holds gVisor's own kernel (the Sentry) and its host threads: the first try killed the **whole
  run** (exit 2, no results) when the fork bomb or the memory hog hit the limits. Now:
  - the in-container runner (`stages.py`) gives every step **per-process limits** with `setrlimit`: at most 100
    processes/threads for the sandbox user (both runtimes), and under gVisor an address-space cap of 768 MB
    (`HMAP_TESTING_MEMORY_MB` + 512) with `MALLOC_ARENA_MAX=2` (glibc's 64 MB per-thread arenas would otherwise stop
    20 threads from starting);
  - under gVisor the cgroup gets headroom for the Sentry: `--memory 1280m`, `--pids-limit 512`;
  - the Node image gets no address-space cap (V8 reserves a huge address space); a JS memory hog under gVisor still
    ends only its own run.

## Measured (2026-10-31, Colima VM: Ubuntu 24.04, aarch64, 2 CPUs, 2 GB; gVisor release-20261026.0)
| | runc | gVisor (`runsc`) |
|---|---|---|
| Install size | — | `runsc` 17 MB + helpers 112 MB in the VM (download 68 MB, SHA-512 checked); VM disk still 17 GB free |
| Kernel the program sees | 6.8.0 (the VM's) | 4.19.0-gvisor (gVisor's Sentry) |
| Container start (10 × `python -c pass`) | 0.093 s | 0.106 s |
| Abuse + seeded + JS + fuzz + mutation tests (`test_sandbox_docker.py`) | 36/36 pass | **36/36 pass** |
| Detection eval (seeded + unseen): results | 100 % / 100 %, 0 false alarms | identical |
| Average pipeline run (seeded + unseen) | 1.60 s | 2.06 s (+29 %) |
| Mutation run, 30 mutants (30 pytest processes) | 13.5 s | 17.8 s (+32 %) |
| JS/TS pipeline (Node image) | 0.54 s | 0.95 s (+76 %) |
| Fuzzing (4 functions, 150 inputs each) | 3/3 found | 3/3 found |

Process-heavy work (Node, many pytest starts) pays the most: every system call goes through the Sentry.

## To install gVisor in Colima (done here once; repeat on a new VM)
```bash
colima ssh -- sudo sh -c 'set -e; URL=https://storage.googleapis.com/gvisor/releases/release/latest/aarch64;
  mkdir -p /tmp/gv && cd /tmp/gv && curl -fsSLO $URL/gvisor.tar.bz2 && curl -fsSLO $URL/gvisor.tar.bz2.sha512 &&
  sha512sum -c gvisor.tar.bz2.sha512 &&
  python3 -c "import tarfile; tarfile.open(\"gvisor.tar.bz2\").extractall(\".\", filter=\"data\")" &&
  install -m 755 runsc containerd-shim-runsc-v1 /usr/local/bin/ && cp -a gvisor-bin /usr/local/bin/ &&
  /usr/local/bin/runsc install && systemctl restart docker && rm -rf /tmp/gv'
HMAP_TESTING_RUNTIME=runsc uv run pytest tests/testing/test_sandbox_docker.py -q -m integration
```
The release layout changed: the old `latest/<arch>/runsc` links return 404; releases are now one
`gvisor.tar.bz2` per architecture (the VM has no `bzip2`, hence the Python one-liner). `colima delete` / a new VM
removes it again.

## Recommendation
Keep runc as the default for the demo laptop (fastest, proven by the attack tests). gVisor is installed in this
Colima VM and passes every sandbox test at ~30 % more time: use `HMAP_TESTING_RUNTIME=runsc` when the code comes from
people you do not trust (a public deployment, an untrusted upload). Firecracker needs a Linux host
with KVM (a cloud VM or a Linux workstation) and a different runner (one micro-VM per run, a root filesystem image);
out of scope for a laptop demo.

## References
Young, Zhu, Caraza-Harter, Arpaci-Dusseau, Arpaci-Dusseau, "The True Cost of Containing: A gVisor Case Study"
(HotCloud 2019) · Agache et al., "Firecracker: Lightweight Virtualization for Serverless Applications" (NSDI 2020) ·
gVisor documentation (architecture, platforms: systrap / KVM) · Docker runtime documentation (`--runtime`).
