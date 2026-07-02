# Try it for real

Hands-on commands to run against a *real* Git repo (this one works fine),
alongside the matching "Group" in the main [README](../README.md). Each
section pairs a real `git` command with the piece of `git_model.py` it
corresponds to.

---

## Group 1 — The Object Model

**Explore `.git/objects` directly** — this repo's own object store is the
real thing, not the toy model, but the same idea: one directory per object.
```
ls .git/objects                       # 2-char prefix dirs (+ pack/, info/)
ls .git/objects/<xx>                  # remaining 38 chars = the filename

git cat-file -t <hash>                # object type: blob / tree / commit
git cat-file -p <hash>                # pretty-print its contents
```
A short prefix (e.g. `git cat-file -p 1a7ad4c`) works too, same as `git log
--oneline` hashes. Start from a commit and follow the pointers down:
`git cat-file -p <commit>` shows its `tree`, `git cat-file -p <tree>` lists
filenames → blob hashes, `git cat-file -p <blob>` shows the raw file
content — the same commit → tree → blob chain `ObjectStore` models.

**Keep remote refs up to date** — your local copies of a remote's refs
(`origin/main`, etc. — `remote_refs` in `Repo`) don't update themselves;
you have to ask.
```
git fetch origin        # update origin/* to match the remote, right now
git fetch --all         # do that for every configured remote
git fetch -p            # also prune local origin/* refs deleted remotely
git branch -vv          # see which remote ref each local branch tracks
```
`git fetch` only moves the `origin/*` pointers — it never touches your own
branches, exactly like `fetch()` in `git_model.py`.

---

## Group 2 — History as a Graph

**Visualize the DAG** — `git log`'s default view is a straight line even
when history isn't; `--graph` draws the actual shape (branches, merges).
```
git log --oneline --graph --all
```
Look for a commit line with two parents (`|\` in the graph) — that's a
merge commit, same as the two-parent commit `merge()` creates.

**Merge, rebase, cherry-pick, for real** — these rewrite/create commits, so
try them on a scratch branch first (`git checkout -b scratch`), not `main`.
```
git merge <branch>              # three-way merge into current branch
git rebase <branch>              # replay current branch's commits onto <branch>
git cherry-pick <commit>         # replay one commit onto current HEAD
```
A conflict on any of these leaves `<<<<<<<` / `=======` / `>>>>>>>` markers
in the affected files and pauses the operation — `git status` tells you
which files and what to do next:
```
git status                       # lists conflicted files
# ...edit the file, resolve the markers by hand...
git add <file>                   # mark it resolved
git rebase --continue             # (or: git commit, for a merge/cherry-pick)
git rebase --abort                # or bail out entirely, back to pre-rebase state
```
This is exactly the `MergeConflict` raised in the demo — real Git just
hands you the conflict to resolve by hand instead of raising an exception.

---

## Group 3 — The Distributed Model

**Clone, fetch, push, pull** — the four remote operations, on a real
remote (swap in any repo URL, including this one):
```
git clone <url>                  # full independent copy: objects + refs
git fetch                        # pull down objects, update origin/* only
git push origin <branch>         # move the remote's ref forward
git pull                         # fetch + merge origin/<branch> into current
```

**Watch a push get rejected** — clone the same repo twice (or ask a
collaborator to push first), then from the *other* clone:
```
git push origin main
# ! [rejected]  main -> main (fetch first)
# error: failed to push some refs...
```
That's the non-fast-forward check from `push()` in `git_model.py` — the
remote has a commit you don't, so pushing would silently erase it. Fix it
the same way the demo does:
```
git pull                         # fetch + merge the missing commit in
git push origin main             # now succeeds
```

---

## Group 4 — Undoing Things & Inspection

**`reset`, at each mode** — try these against a throwaway commit so you
can see the difference:
```
git reset --soft <commit>        # branch pointer only
git reset --mixed <commit>       # + staging (this is the default)
git reset --hard <commit>        # + working dir too (discards uncommitted work)
```

**`revert`** — the safe, forward-only undo:
```
git revert <commit>
```
Creates a new commit undoing `<commit>`'s changes; nothing already pushed
becomes unreachable, unlike `reset`.

**The reflog** — your local safety net, independent of the object store:
```
git reflog
```
Every HEAD movement (commit, checkout, reset, rebase, merge...) gets an
entry here, exactly like `Repo.reflog` in the model. This is how you find
a commit again after a `reset --hard` "loses" it.

**Find and inspect dangling commits** — objects still in `.git/objects` but
unreachable from any ref (real Git's own version of `dangling_commits()`):
```
git fsck --unreachable            # lists dangling commits/blobs/trees
git cat-file -p <dangling-hash>   # inspect one before it's gone
git gc                            # eventually prunes unreachable objects for real
```
