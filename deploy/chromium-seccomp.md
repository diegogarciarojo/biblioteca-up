# Chromium sandbox profile

`chromium-seccomp.json` is the profile recommended by the official Playwright
Docker documentation for browsers that read external websites. It retains the
default deny action and allows user namespace creation for Chromium's sandbox.

Source: https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json

Retrieved: 2026-09-28. Upstream repository license: Apache-2.0.

The worker uses a non-root account, this profile, a container init process, and
512 MB of shared memory. It does not request privileged mode or SYS_ADMIN.
Linux container startup still needs verification on the target VPS; a Windows
browser launch does not validate Linux kernel namespace support.
