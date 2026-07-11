## Purpose and reader

- Purpose: show how module imports quietly become application lifecycle and dependency architecture.
- Reader: a Python engineer who has inherited slow or fragile startup.
- Public boundary: use generic examples. Do not identify internal services, feature flags, endpoints, incidents, or startup measurements.

## “Just importing it”

Known material: imports can perform network I/O, initialize clients, register task machinery, build routing graphs, or warm caches.

CHRIS: Which category surprised you most when you measured import time?

## Process roles are different programs

CHRIS: Which work belongs in a web process, worker, pre-fork master, CI check, or first-use path?

CHRIS: What broke when one role imported machinery intended for another?

## Lazy does not mean unbounded

CHRIS: How should first-use initialization handle timeouts, failure, caching, and retries?

## The design rule

CHRIS: What should be safe to assume when importing an application module?
