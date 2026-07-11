## Purpose and reader

- Purpose: explain why adding an LRU is not a complete cache design.
- Reader: an engineer working with multiprocess services or large in-memory objects.
- Public boundary: use generic process and object examples. Do not publish private topology, cache keys, production memory figures, or incident details.

## The entry count lied by omission

Known material: a bounded cache can still be badly sized when each entry retains a large object graph.

CHRIS: What made the retained size visible?

CHRIS: What did callers actually need compared with what the cache retained?

## Where the cache is built matters

Known material: expensive compiled objects may be wasteful when built privately in every worker and useful when built once where copy-on-write sharing is possible.

CHRIS: What lifecycle or process boundary changed the economics of the cache?

## The design checklist

CHRIS: Which questions now belong in every cache review: entry size, key cardinality, sharing, eviction, construction cost, or something else?
