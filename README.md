# mini-git
A toy, from-scratch model of Git's core mechanics.

This is a small, runnable Python model of how Git actually works underneath —
built for conceptual clarity, not as a real implementation. It's meant to be
read alongside running it: every concept below has corresponding code in
`git_model.py`, organized into the same four groups.

**Run it:**
```
python3 git_model.py
```

It prints a guided tour through every concept, in dependency order, with
commentary. Read the output next to this README section by section.

---

## The throughline: one chain of forced decisions

Git wasn't designed as a feature list. Linus Torvalds wrote it in about 10
days in 2005, after the Linux kernel project lost access to its previous
tool (BitKeeper) over a licensing dispute. Every major piece of Git exists
because an earlier piece created a new problem that needed solving. Read
top to bottom, it's one continuous chain:

> can't coordinate via a central server → hash the content so it names
> itself → make pointers to hashes cheap (branches) → structure "saving" as
> three deliberate stages → let commits branch and merge → let every clone
> be a fully independent repository → provide safe ways to undo and inspect
> → keep the object store efficient as it grows.

The four groups below are that chain, broken into stages.

---

## Group 1 — The Object Model (`git_model.py`: `ObjectStore`, `Repo` basics)

**Problem:** No central authority can hand out IDs, because Git was built
for fully offline, disconnected collaboration (kernel developers emailing
patches, no server reachable). Someone needs to be able to name a piece of
data *without asking anyone else first*.

**Solution:** Content names itself. Every object — a file's contents (a
**blob**), a directory listing (a **tree**), a snapshot-plus-metadata (a
**commit**) — is hashed from its own content. Two identical files anywhere,
any time, produce the identical hash and are stored once.

**Problem:** Referring to "the current state of a line of work" by a full
hash is unwieldy, and old tools (CVS, SVN) made branching *expensive*
(literally copying directories), so people avoided it.

**Solution:** A **branch** (`Repo.refs`) is just a name pointing at a commit
hash — a few bytes, free to create, free to delete. **HEAD** is a pointer to
whichever branch you're on (or, "detached," directly at a commit).

**Problem:** Committing shouldn't be an automatic snapshot of whatever
happens to be on disk at that instant — you want the ability to construct a
commit deliberately, one file at a time.

**Solution:** Three explicit stages: the **working directory** (your actual
files), the **staging area / index** (what's about to be committed), and
**HEAD** (the last commit). `git add` copies working dir → staging;
`git commit` turns staging into a real commit object and moves the branch
pointer forward.

**Try it:** the first three sections of the demo output. Watch how the same
string always produces the same hash, and how `refs` is genuinely just a
`{name: hash}` dictionary.

---

## Group 2 — History as a Graph (`git_model.py`: `merge`, `rebase`, `cherry_pick`)

**Problem:** Real engineering work isn't linear — people work in parallel
and need their work to reconverge later. A straight-line history model
can't represent that.

**Solution:** A commit can have more than one parent (`store_commit`'s
`parents` list). This turns history from a list into a **DAG** (directed
acyclic graph). Once that's true, `merge`, `rebase`, and `cherry-pick` are
just three different operations *on that graph*:

- **`merge`** — walks the graph backward from both branch tips to find their
  **common ancestor**, then does a **three-way comparison**: for each file,
  if only one side changed it, take that side; if both sides changed it
  identically, fine; if both sides changed it *differently* → **conflict**.
  The result becomes a new commit with **two parents** — history is
  preserved exactly as it happened.
- **`rebase`** — takes your commits since the common ancestor and **replays**
  their changes on top of the other branch's tip, one at a time. Each
  replayed commit gets a brand-new hash (same content, different parent →
  different commit object). The demo proves this: it prints the commit hash
  before and after rebase and shows they differ, and shows the *old* commit
  is still sitting in the object store but is no longer reachable from any
  ref — this is exactly why rebasing a branch other people already have is
  dangerous: their copy and your rewritten copy no longer share history.
- **`cherry-pick`** — the same "replay" idea, scoped to just *one* commit
  instead of a whole branch.

**Try it:** the merge/conflict/rebase/cherry-pick sections. Pay attention to
which commit hashes change and which don't — that's the whole lesson.

---

## Group 3 — The Distributed Model (`git_model.py`: `clone`, `fetch`, `push`, `pull`)

**Problem:** No single copy of a repository should be more "real" than
another, because contributors need to work fully offline for long stretches.
A thin-client model (talk to the server for everything) doesn't survive
that constraint.

**Solution:** Every `clone()` is a **complete, independent `Repo`** — its
own full object store, its own refs. "The remote" (`origin`) is just another
`Repo` that the team has agreed to treat as authoritative, not a
fundamentally different kind of thing.

- **`fetch`** — copies new objects from the remote and updates
  remote-tracking refs (`origin/main`) — it never touches your own branches.
- **`push`** — copies your objects to the remote and moves the remote's ref
  forward, **but only if it's a fast-forward** (the remote's current commit
  must be an ancestor of what you're pushing). This is a safety check, not
  an arbitrary restriction: it stops you from silently erasing commits the
  remote has that you don't. `force=True` skips the check.
- **`pull`** — fetch, then merge the tracking ref into your current branch.

**Try it:** the last two sections of the demo. Two independent clones
(`dev_a`, `dev_b`) both start from the same commit; `dev_a` pushes first;
`dev_b`'s push is **rejected** until it pulls dev_a's work in.

---

## Group 4 — Undoing Things & Inspection (`git_model.py`: `reset`, `revert`, `dangling_commits`, `Repo.reflog`)

**Problem:** Once history can be rewritten (Group 2) and pointers can be
moved (Group 1), mistakes need clearly different, well-understood ways to
be undone — "undo" isn't one operation, it's several, with very different
safety properties.

**Solution:** Three tools, each touching a different part of the model:

- **`reset(mode="soft"/"mixed"/"hard")`** — moves the **branch pointer**
  backward (and, for `mixed`/`hard`, overwrites staging/working dir too).
  This **rewrites** what the branch points to. Only safe if nobody else has
  already seen the commit you're abandoning.
- **`revert`** — creates a **new** commit whose content undoes an earlier
  commit's changes. History only ever grows forward. This is the only one
  of the three that's safe on a branch other people already have — it never
  makes an existing commit unreachable.
- **`dangling_commits`** — commits that still exist in the object store but
  aren't reachable from any ref anymore (e.g. after a hard reset). Real Git
  calls this exact state "dangling," and it's what `git reflog` lets you
  recover from, and what `git gc` eventually cleans up permanently.

`Repo.reflog` is a private log of every time HEAD moved — a safety net for
"how do I get back to where I was," independent of the object store itself.

**Try it:** the reset/revert sections. Notice that after `reset --hard`, the
"mistake" commit is still physically present in `repo.store.objects` — it's
just no longer reachable — and the reflog still remembers it.

---

## What's deliberately simplified or skipped

This model is built for the *shape* of the ideas, not full fidelity. If
something below matters to your actual work, treat it as a pointer to go
learn the real thing — this code won't teach it further.

| Topic | Status here | Why skipped / simplified |
|---|---|---|
| Real Git hash format (SHA-1 header, zlib compression) | Simplified | We hash `"type:content"` directly; real Git's exact byte format doesn't change the lesson. |
| SHA-1 → SHA-256 transition | Not modeled | A security/scale detail on top of the same core idea — content-addressing — not a new concept. |
| Nested trees (subfolders) | Flattened to one level | Group 1's original discussion already covers nesting conceptually; flattening keeps merge/rebase code readable without losing the point. |
| Line-level diffing (real `diff3`) | File-level only | Real conflict detection compares individual lines. File-level three-way comparison teaches the *logic* of conflicts without needing a diff algorithm. |
| Interactive rebase (squash, reorder, edit) | Not implemented | Same "replay" mechanic as plain rebase, just with commits reordered/combined first — not a new underlying idea. |
| Packfiles, `git gc`, `git fsck` | Not implemented | This model never compacts storage; every object lives forever in a dict. Real Git needs this at scale (years of history); it doesn't change how the *object model* works, only its storage efficiency. |
| Submodules / subtrees | Not implemented | A genuinely separate feature for nesting one repo inside another — not a consequence of the object model, safe to learn only if you hit it. |
| Git hooks | Not implemented | An extension/automation mechanism layered on top of commands, not part of the core data model this project is illustrating. |
| `.gitignore` | Not implemented | A working-directory convenience feature; orthogonal to the object/graph model. |
| Authentication, network transport | Not modeled | `push`/`fetch`/`pull` here just copy Python dicts between two `Repo` objects in memory — real Git's transport (SSH, HTTPS) is a separate concern from the data model. |

---

## Why this matters day-to-day (the "best practices" payoff)

A few real rules of thumb fall directly out of what's modeled here — not as
arbitrary etiquette, but as consequences you can now see mechanically:

- **"Never rebase a shared/public branch."** The rebase demo shows *why*:
  rebased commits get new hashes. If someone already pulled the old ones,
  your rewritten branch and their copy no longer share history — their next
  pull/push will look like a conflict or a divergence, not a simple update.
- **"Prefer `revert` over `reset` once something is pushed."** `reset`
  rewrites what the branch points to; `revert` only ever adds. Once other
  people can see a commit, only one of these two is safe.
- **"Pull (or fetch+rebase) before you push."** The `push` rejection in the
  demo isn't Git being difficult — it's the fast-forward check refusing to
  let you silently overwrite commits you haven't even seen yet.
- **"Force-push is dangerous, use `--force-with-lease` in real Git."**
  `force=True` in `push()` here shows exactly what it skips: the check that
  stops you from erasing someone else's already-pushed work.
- **Merge conflicts are not mysterious.** They're a direct, visible
  consequence of two branches changing the same file differently since
  their common ancestor — which is exactly what `three_way_merge` computes
  and prints in the demo.