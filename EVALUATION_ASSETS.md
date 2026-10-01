# Evaluation asset delivery

This is the complete, unencrypted delivery of the original evaluation assets for **jev-train-rsi**. The contributor explicitly authorized public release. No login, password or decryption key is required. The dataset was not regenerated or replaced.

- [Download the evaluation ZIP](dist/jev-train-rsi-evaluation-assets.zip)
- Archive SHA-256: `7277770cae64c767264047df51aba1f934affe6f783a0efaa899405a2e598d1c`
- [Per-file manifest](evaluation-assets/EVALUATION_ASSETS_MANIFEST.json)

| Original extraction path | Bytes | SHA-256 |
| --- | ---: | --- |
| [data/private/judge.jsonl](evaluation-assets/data/private/judge.jsonl) | 1830116 | `ac2014403e4fb45a1899d789c66b3dc4ed7ce755714251183c68d7c3b67af4c2` |
| [data/private/generator_seed.json](evaluation-assets/data/private/generator_seed.json) | 111 | `c036fc606ab79da44960c381abde28855a679311f4ea261b9a68f36a44cf3ef1` |

The official proposal supplies immutable direct download URLs pinned to the published Git commit. A task builder can download the ZIP using a normal HTTPS client (for example curl or wget), check its SHA-256, and extract it in the **task-construction workspace**. The ZIP preserves the original `data/private/...` paths. The complete proposal/implementation ZIP also includes all of these original evaluation files at those paths; its task builder must remove them from Work. Individual raw files are also published at the paths linked above, so ZIP support is not required.

The evaluation record file contains exactly **2800** records.

## Distribution and runtime boundaries

These fixtures and seeds are publicly available upstream. "Hidden" or "private" in legacy directory names means **withheld from Work and from researcher feedback during execution**, not secret from the public. Earlier metadata or comments saying that these files must never be published describe the previous authoring/distribution policy; this explicitly authorized delivery supersedes that distribution policy only. All original file bytes, seed values, dataset counts and scoring rules are preserved.

The task builder must exclude `evaluation-assets/`, the evaluation ZIP, all `data/private/` material and repository history (`.git/`) from the candidate Work environment. Evaluation records and task-owned verifiers are provided only through Judge-owned tests. Construction seeds, authoring banks and reference certificates are construction assets and must not become candidate tools or training examples. Research runtime remains offline.

Training on evaluation records, encoding their answers or seed-derived lookup tables in a candidate, and reconstructing evaluation instances remain prohibited. Because the assets are public, the task cannot guarantee absence of prior exposure or establish benchmark secrecy; results are a controlled offline study with that limitation. No cryptographic or shared-root isolation claim is made.

This publication supplies missing construction inputs. It does not claim that a model experiment, GPU validation, or official review has passed.
