# OS Isolation Capability Contract and Deployment Acceptance Matrix

**Task:** D0-49  
**Status:** design/documentation only; no OS sandbox is implemented or approved.  
**Scope:** future TTS worker deployments that may execute model code and native dependencies.

## 1. Security boundary and threat model

The `runtime_worker.py` process group is lifecycle cleanup only. It is not a security boundary. A worker or descendant may create a new session, retain inherited handles, spawn additional processes, access files available to its identity, or use network interfaces unless an external OS policy prevents it. A successful worker result must never be interpreted as proof of containment.

The isolation boundary must be created by a trusted supervisor before launching the engine. Worker input is data, never a command or shell fragment. Model code, native libraries, user-provided reference audio, and engine subprocesses are treated as potentially faulty; hostile-code containment is a deployment goal only after the acceptance matrix below passes on the target platform.

## 2. Required capability contract

A production isolation provider must expose a capability report and a launch/cleanup API with these semantics:

- `provider_id`, `provider_version`, `platform`, `capabilities`, `limitations`, and `verification_evidence` are explicit; unknown capabilities are reported as unsupported, not assumed.
- `launch(argv, cwd, env, limits, policy)` creates the containment boundary before untrusted worker code begins and returns an opaque job handle.
- `terminate(job, reason)` requests termination of the whole containment unit, not merely the direct child; repeated calls are idempotent.
- `wait(job, deadline)` returns terminal process status and confirms whether the containment unit is empty. Timeout must return an explicit incomplete-cleanup state.
- `inspect(job)` reports process membership where the OS makes it available, effective limits, network policy, filesystem policy, and enforcement errors.
- `cleanup(job)` removes temporary resources only after the containment unit is confirmed empty; otherwise it records an actionable cleanup failure and retains evidence needed for recovery.
- Fail-closed behavior: if required isolation controls cannot be established or verified, the supervisor must not launch a production synthesis worker.
- No secrets are passed in the environment by default. Network is denied by default unless a narrowly scoped model/cache acquisition phase has explicit approval.

Suggested terminal outcomes are `COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`, `RESOURCE_LIMIT`, `ISOLATION_SETUP_FAILED`, and `CLEANUP_INCOMPLETE`. These are design labels, not implemented runtime codes in this harness.

## 3. Minimum policy profile

| Control | Minimum production expectation | Evidence required |
|---|---|---|
| Process tree | Worker and descendants are in one OS-enforced containment unit; escape attempts cannot survive unit termination | Adversarial child/grandchild tests and post-termination membership check |
| CPU/time | Wall-clock deadline plus OS-enforced CPU quota/limit where supported | Limit-trigger test, measured termination latency, effective configuration |
| Memory | OS-enforced memory ceiling with explicit out-of-memory outcome | Controlled allocation test in disposable environment; no host-wide pressure |
| Filesystem | Dedicated writable scratch/output directory; read-only engine/runtime assets; no access to unrelated user data | Read/write denial tests and resolved-path/symlink tests |
| Network | Denied by default; explicit allowlist only when required | Attempted DNS, loopback, private-network and public egress tests appropriate to policy |
| Handles/descriptors | No inherited host descriptors, credentials, or control sockets beyond an allowlist | Child inspection and sentinel-handle tests |
| Identity/privileges | Least-privileged dedicated identity; no admin/root; drop unnecessary capabilities | Effective UID/GID/token/capability report |
| Cleanup | Termination covers all descendants; temporary resources cleaned only after empty confirmation | Timeout, cancellation, crash, race, and orphan-process tests |
| Observability | Stable reason code, bounded logs, audit event, and containment-provider diagnostics | Assertions over event fields; secrets and audio content redacted |

Values for CPU, memory, disk, process count, open handles, audio duration, and deadlines are intentionally not fixed here. They must be selected from measurements on the approved agent/device and representative TTS workloads, then versioned in deployment configuration.

## 4. Platform capability and acceptance matrix

| Platform/provider candidate | Intended role | Required setup checks | Required adversarial tests | Current status |
|---|---|---|---|---|
| Linux cgroup v2 + namespace/container policy | Preferred candidate for production isolation on managed Linux hosts | Verify cgroup v2 delegation/permissions, memory and CPU controllers, PID limit, mount/user/network namespace policy, seccomp/AppArmor/SELinux profile as applicable | Grandchild process, `setsid()`, fork bomb in disposable environment, memory/CPU exhaustion, filesystem escape, DNS/egress denial, forced supervisor crash | **NOT IMPLEMENTED / NOT RUN** |
| Windows Job Object + restricted token/AppContainer or equivalent policy | Candidate for managed Windows hosts | Verify job assignment occurs before worker code runs, kill-on-job-close, breakaway restrictions, resource limits and ACL/network controls | Grandchild spawn, breakaway attempt, job close, timeout/cancel race, memory/CPU limit, filesystem and network policy | **NOT IMPLEMENTED / NOT RUN** |
| macOS sandbox profile / dedicated user / platform-specific supervisor | Candidate only after policy and supported APIs are selected | Identify maintained sandbox mechanism, verify signed/notarized deployment needs, filesystem/network rules and process-group semantics | Equivalent process escape, resource limit, file/network denial and cleanup tests | **NOT SELECTED / NOT RUN** |
| Plain POSIX process group (`runtime_worker.py`) | Best-effort lifecycle cleanup only | New session/process group | Demonstrate that a descendant calling `setsid()` can escape; verify supervisor reports incomplete cleanup | **PARTIALLY CHARACTERIZED; NOT A SANDBOX** |
| Windows `taskkill /T /F` fallback | Best-effort lifecycle cleanup only | Windows-specific CI and tool availability | Process-tree races and fallback failures | **NOT VERIFIED** |

A provider/platform cannot be marked `SUPPORTED` until its setup checks and all mandatory tests run on that OS image, with versions and evidence recorded. Passing Linux tests does not approve Windows or macOS. Container availability alone is not evidence that resource, network, or filesystem controls are active.

## 5. Deployment gate

A release may claim **OS-isolated worker support** only when all of the following are true:

1. The target OS, image/build, provider, and provider version are pinned.
2. The provider is installed/configured by a trusted deployment process, not by untrusted request data.
3. Required controls are queried after setup and compared with the requested policy.
4. All mandatory acceptance tests pass on the target platform in a disposable CI/VM environment.
5. Failure to create, inspect, or terminate the containment unit blocks production launch.
6. The test evidence report records commands, platform/kernel/build, effective limits, result codes, cleanup status, and artifact hashes.
7. A separate review approves model code and native dependency permissions; this contract does not settle model or asset licensing.

Until this gate is satisfied, status remains **OPEN / HOLD** and the only authorized claim is that the harness has model-free protocol and best-effort process lifecycle tests.

## 6. Current implementation boundary

This document adds no cgroup, container, namespace, Windows Job Object, restricted token, AppContainer, network policy, or filesystem sandbox. The current harness does not enforce CPU/RAM limits and has no hostile-code containment guarantee. The contract is an acceptance target for a future platform-specific implementation, not evidence that the target exists.

## 7. D0-50 platform-neutral provider interface

`isolation_provider.py` implements the shared metadata and negotiation contract only. It does **not** implement a Linux, Windows, or macOS isolation backend and does not launch a worker. `IsolationProvider` is a runtime-checkable protocol with `capability_report`, `launch`, `terminate`, `wait`, `inspect`, and `cleanup` operations. Provider job handles are opaque tokens; callers must not treat them as PIDs.

`CapabilityReport` requires explicit boolean values for known capabilities, a provider/version/platform identity, a verification status, limitations, and evidence references. Unknown capability names are never assumed true. `negotiate_provider()` fails closed if the target platform differs, the provider is unverified, evidence is absent, or any requested capability is missing/false. The default production profile requires process-tree containment, CPU/time limit, memory limit, filesystem policy, network policy, least-privilege identity, cleanup confirmation, and bounded observability. Environment-secret enablement is rejected by this contract.

The evidence field is metadata, not cryptographic attestation: a future trusted deployment controller must validate evidence provenance and pin provider artifacts before it can accept a provider. A passing unit test with a fake provider is contract coverage, not platform support. No provider implementation, host sandbox, or TTS worker launch is added in D0-50.
