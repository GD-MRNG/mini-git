"""
git_model.py — a toy, from-scratch model of Git's core mechanics.

This is NOT real Git (no zlib, no packfiles, no on-disk .git format, no
line-level diffing). It's a simplified but *functionally real* model:
hashes are genuinely computed from content, branches are genuinely just
pointers, merges genuinely walk a real parent graph to find a common
ancestor, etc. The goal is conceptual clarity, not compatibility with
real Git.

See README.md for the "why" behind each piece, and for a list of things
that are simplified or skipped entirely, and why.

Run this file directly to see a guided tour: `python3 git_model.py`
"""

import hashlib
import json


# ============================================================
# GROUP 1: THE OBJECT MODEL
# Problem: no central server can hand out IDs, since work happens offline
# and disconnected. Solution: let content name itself via hashing.
# ============================================================

class ObjectStore:
    """The '.git/objects' equivalent: hash -> object."""

    def __init__(self):
        self.objects = {}

    def _hash(self, obj_type: str, payload: str) -> str:
        # Real Git: SHA1("<type> <byte-length>\0<content>"). We simplify
        # the header but keep the essential idea: hash = f(type, content).
        return hashlib.sha1(f"{obj_type}:{payload}".encode()).hexdigest()[:10]

    def store_blob(self, content: str) -> str:
        h = self._hash("blob", content)
        self.objects[h] = {"type": "blob", "content": content}
        return h

    def store_tree(self, entries: dict) -> str:
        """entries: {filename: blob_hash}. Flat only (no subfolders) —
        real Git trees nest recursively; we flatten for readability.
        See README for why this simplification doesn't lose the lesson."""
        payload = json.dumps(entries, sort_keys=True)
        h = self._hash("tree", payload)
        self.objects[h] = {"type": "tree", "entries": dict(entries)}
        return h

    def store_commit(self, tree_hash: str, parents: list, message: str, author="glenn") -> str:
        payload = json.dumps(
            {"tree": tree_hash, "parents": parents, "message": message, "author": author},
            sort_keys=True,
        )
        h = self._hash("commit", payload)
        self.objects[h] = {
            "type": "commit",
            "tree": tree_hash,
            "parents": parents,   # list, not single — this is what allows merge commits
            "message": message,
            "author": author,
        }
        return h

    def get(self, h: str) -> dict:
        return self.objects[h]

    def merge_from(self, other: "ObjectStore"):
        """Copy all objects from another store into this one — this is
        literally what 'fetch' does at the object level."""
        self.objects.update(other.objects)


# ============================================================
# GROUP 1 (cont'd): REFS + THREE TREES
# Problem: branching in old VCSs meant copying directories — expensive,
# so people avoided it. Solution: a branch is just a name pointing at a
# commit hash. Problem: committing shouldn't silently snapshot whatever's
# on disk. Solution: three explicit stages (working dir / staging / HEAD).
# ============================================================

class Repo:
    def __init__(self, name="repo"):
        self.name = name
        self.store = ObjectStore()
        self.refs = {}            # branch name -> commit hash      ("refs/heads/*")
        self.remote_refs = {}     # "origin/main" -> commit hash    ("refs/remotes/*")
        self.head = "main"        # HEAD points at a branch name...
        self.head_detached = False  # ...unless this is True, then head is a raw commit hash
        self.working_dir = {}     # filename -> content   (Tree 1: what's on disk)
        self.staging = {}         # filename -> content   (Tree 2: proposed next commit)
        self.reflog = []          # private journal of every HEAD movement

    # ---- helpers ----
    def current_commit(self):
        return self.head if self.head_detached else self.refs.get(self.head)

    def _log(self, action, old, new):
        self.reflog.append({"action": action, "old": old, "new": new})

    def tree_of(self, commit_hash):
        """Resolve a commit hash down to its flat {filename: blob_hash} entries."""
        if commit_hash is None:
            return {}
        commit = self.store.get(commit_hash)
        return dict(self.store.get(commit["tree"])["entries"])

    def content_of(self, commit_hash, filename):
        entries = self.tree_of(commit_hash)
        if filename not in entries:
            return None
        return self.store.get(entries[filename])["content"]

    def ancestors(self, commit_hash):
        """All commits reachable by walking parent pointers (including itself)."""
        seen = set()
        stack = [commit_hash] if commit_hash else []
        while stack:
            h = stack.pop()
            if h in seen or h is None:
                continue
            seen.add(h)
            stack.extend(self.store.get(h)["parents"])
        return seen

    def common_ancestor(self, a, b):
        """The merge base: newest commit reachable from both a and b."""
        a_ancestors = self.ancestors(a)
        # BFS from b to find the FIRST (closest) ancestor also in a's set
        stack, seen = [b], set()
        while stack:
            h = stack.pop(0)
            if h in seen or h is None:
                continue
            seen.add(h)
            if h in a_ancestors:
                return h
            stack.extend(self.store.get(h)["parents"])
        return None

    # ---- Group 1: everyday commands ----
    def write_file(self, name, content):
        self.working_dir[name] = content

    def add(self, name):
        """git add: copy working dir -> staging."""
        self.staging[name] = self.working_dir[name]

    def status(self):
        unstaged = {f: c for f, c in self.working_dir.items() if self.staging.get(f) != c}
        staged_vs_head = {}
        head_entries = self.tree_of(self.current_commit())
        for f, c in self.staging.items():
            head_blob = head_entries.get(f)
            head_content = self.store.get(head_blob)["content"] if head_blob else None
            if head_content != c:
                staged_vs_head[f] = c
        return {"staged (to be committed)": staged_vs_head, "not staged (working dir changes)": unstaged}

    def commit(self, message, parents_override=None):
        """git commit: staging -> a real commit object, branch ref moves forward."""
        entries = {name: self.store.store_blob(content) for name, content in self.staging.items()}
        tree_hash = self.store.store_tree(entries)
        parent = self.current_commit()
        parents = parents_override if parents_override is not None else ([parent] if parent else [])
        commit_hash = self.store.store_commit(tree_hash, parents, message)

        old = self.head
        if self.head_detached:
            self.head = commit_hash
        else:
            self.refs[self.head] = commit_hash
        self._log("commit", old, commit_hash)
        return commit_hash

    def branch(self, name):
        """git branch <name>: new pointer, same commit as HEAD. O(1) — no copying."""
        self.refs[name] = self.current_commit()

    def checkout(self, name_or_hash):
        """git checkout: move HEAD, and load that commit's files into staging/working dir."""
        old = self.head
        if name_or_hash in self.refs:
            self.head = name_or_hash
            self.head_detached = False
            target = self.refs[name_or_hash]
        else:
            self.head = name_or_hash
            self.head_detached = True
            target = name_or_hash
        entries = self.tree_of(target)
        loaded = {f: self.store.get(b)["content"] for f, b in entries.items()}
        self.working_dir = dict(loaded)
        self.staging = dict(loaded)
        self._log("checkout", old, self.head)

    def log(self, limit=10):
        """Walk parent pointers from HEAD back — first-parent only, for readability."""
        h = self.current_commit()
        chain = []
        while h and len(chain) < limit:
            c = self.store.get(h)
            chain.append((h, c["message"], c["parents"]))
            h = c["parents"][0] if c["parents"] else None
        return chain


# ============================================================
# GROUP 2: HISTORY AS A GRAPH
# Problem: parallel work needs to diverge and reconverge, not just
# form a straight line. Solution: a commit can have >1 parent.
# merge/rebase/cherry-pick are three different ways of using that.
# ============================================================

class MergeConflict(Exception):
    def __init__(self, files):
        self.files = files
        super().__init__(f"Conflict in: {', '.join(files)}")


def three_way_merge(base_entries, ours_entries, theirs_entries):
    """
    The heart of 'merge'. For every file, compare our version and their
    version against the common ancestor's version:
      - unchanged on both sides           -> keep it
      - only WE changed it                -> take ours
      - only THEY changed it               -> take theirs
      - BOTH changed it, to different things -> CONFLICT
    Real Git does this at the line level (diff3); we do it at the file
    level, which is a genuine simplification — see README.
    """
    files = set(base_entries) | set(ours_entries) | set(theirs_entries)
    result, conflicts = {}, []
    for f in files:
        base = base_entries.get(f)
        ours = ours_entries.get(f)
        theirs = theirs_entries.get(f)
        if ours == theirs:
            if ours is not None:
                result[f] = ours
        elif ours == base:
            if theirs is not None:
                result[f] = theirs
        elif theirs == base:
            if ours is not None:
                result[f] = ours
        else:
            conflicts.append(f)
    return result, conflicts


def merge(repo: Repo, other_branch: str, message=None):
    """git merge <other_branch>."""
    ours = repo.current_commit()
    theirs = repo.refs[other_branch]
    base = repo.common_ancestor(ours, theirs)

    if base == theirs:
        return {"status": "already-up-to-date"}
    if base == ours:
        # Fast-forward: our branch hasn't diverged, just move the pointer.
        repo.refs[repo.head] = theirs
        repo.checkout(repo.head)
        return {"status": "fast-forward", "commit": theirs}

    base_e = repo.tree_of(base)
    ours_blob_e = repo.tree_of(ours)
    theirs_blob_e = repo.tree_of(theirs)
    result_blobs, conflicts = three_way_merge(base_e, ours_blob_e, theirs_blob_e)
    if conflicts:
        raise MergeConflict(conflicts)

    tree_hash = repo.store.store_tree(result_blobs)
    commit_hash = repo.store.store_commit(
        tree_hash, [ours, theirs], message or f"Merge branch '{other_branch}'"
    )
    repo.refs[repo.head] = commit_hash
    repo.checkout(repo.head)
    return {"status": "merge-commit", "commit": commit_hash}


def rebase(repo: Repo, onto_branch: str):
    """
    git rebase <onto_branch>: replay MY commits (since our common ancestor)
    on top of onto_branch's tip. Each replayed commit gets a brand-new hash
    — same content, different parent, so a different commit object entirely.
    This is why rebase rewrites history and why it's unsafe once pushed.
    """
    mine = repo.current_commit()
    onto = repo.refs[onto_branch]
    base = repo.common_ancestor(mine, onto)

    # Collect my commits since base, oldest first
    my_commits = []
    h = mine
    while h != base:
        c = repo.store.get(h)
        my_commits.append((h, c))
        h = c["parents"][0] if c["parents"] else None
    my_commits.reverse()

    new_tip = onto
    for old_hash, c in my_commits:
        old_parent_tree = repo.tree_of(c["parents"][0] if c["parents"] else None)
        my_tree = repo.tree_of(old_hash)
        changed = {f: v for f, v in my_tree.items() if old_parent_tree.get(f) != v}

        new_base_tree = repo.tree_of(new_tip)
        result_blobs, conflicts = three_way_merge(old_parent_tree, new_base_tree, {**new_base_tree, **changed})
        # ^ treat "new base" as ours, "old commit's changes applied" as theirs
        if conflicts:
            raise MergeConflict(conflicts)

        tree_hash = repo.store.store_tree(result_blobs)
        new_tip = repo.store.store_commit(tree_hash, [new_tip], c["message"])

    old = repo.head
    repo.refs[repo.head] = new_tip
    repo.checkout(repo.head)
    repo._log("rebase", old, new_tip)
    return new_tip


def cherry_pick(repo: Repo, commit_hash: str):
    """git cherry-pick <commit>: replay ONE commit's changes onto current HEAD."""
    c = repo.store.get(commit_hash)
    parent_tree = repo.tree_of(c["parents"][0] if c["parents"] else None)
    commit_tree = repo.tree_of(commit_hash)
    changed = {f: v for f, v in commit_tree.items() if parent_tree.get(f) != v}

    current_tree = repo.tree_of(repo.current_commit())
    result_blobs, conflicts = three_way_merge(parent_tree, current_tree, {**current_tree, **changed})
    if conflicts:
        raise MergeConflict(conflicts)

    tree_hash = repo.store.store_tree(result_blobs)
    new_hash = repo.store.store_commit(tree_hash, [repo.current_commit()], c["message"])
    old = repo.head
    repo.refs[repo.head] = new_hash
    repo.checkout(repo.head)
    repo._log("cherry-pick", old, new_hash)
    return new_hash


# ============================================================
# GROUP 4: UNDOING THINGS (reset / revert) + INSPECTION (reflog)
# Problem: once history can be rewritten and pointers can move, mistakes
# need well-understood, differently-scoped undo tools.
# ============================================================

def reset(repo: Repo, target_hash: str, mode="mixed"):
    """
    git reset --soft/--mixed/--hard <target>
      soft:  move branch pointer only
      mixed: + also reset staging to match target (default)
      hard:  + also overwrite working dir (DESTROYS uncommitted work)
    The old commit isn't deleted — it becomes 'dangling': still in the
    object store, unreachable from any ref, recoverable via reflog.
    """
    old = repo.current_commit()
    if repo.head_detached:
        repo.head = target_hash
    else:
        repo.refs[repo.head] = target_hash
    repo._log(f"reset --{mode}", old, target_hash)

    if mode in ("mixed", "hard"):
        entries = repo.tree_of(target_hash)
        repo.staging = {f: repo.store.get(b)["content"] for f, b in entries.items()}
    if mode == "hard":
        repo.working_dir = dict(repo.staging)


def revert(repo: Repo, commit_hash: str):
    """
    git revert <commit>: create a NEW commit that undoes commit_hash's
    changes. History only grows forward — this is why it's the only
    safe 'undo' on a branch other people already have.
    """
    c = repo.store.get(commit_hash)
    parent_hash = c["parents"][0] if c["parents"] else None
    parent_tree = repo.tree_of(parent_hash)
    commit_tree = repo.tree_of(commit_hash)

    current_tree = repo.tree_of(repo.current_commit())
    result = dict(current_tree)
    for f in set(parent_tree) | set(commit_tree):
        if commit_tree.get(f) != parent_tree.get(f):
            if f in parent_tree:
                result[f] = parent_tree[f]          # restore old content
            else:
                result.pop(f, None)                  # file was added by commit_hash -> remove it

    tree_hash = repo.store.store_tree(result)
    new_hash = repo.store.store_commit(tree_hash, [repo.current_commit()], f"Revert \"{c['message']}\"")
    old = repo.head
    repo.refs[repo.head] = new_hash
    repo.checkout(repo.head)
    repo._log("revert", old, new_hash)
    return new_hash


def dangling_commits(repo: Repo):
    """Objects that exist in the store but aren't reachable from any ref
    or the reflog's 'new' side isn't even needed — anything not reachable
    from current refs at all. This is what 'git gc' would eventually prune."""
    reachable = set()
    for ref_hash in repo.refs.values():
        reachable |= repo.ancestors(ref_hash)
    all_commits = {h for h, o in repo.store.objects.items() if o["type"] == "commit"}
    return all_commits - reachable


# ============================================================
# GROUP 3: THE DISTRIBUTED MODEL
# Problem: no single copy should be more "real" than another, since
# people need to work fully offline. Solution: every clone is a
# complete, independent Repo. "The remote" is just another Repo we
# happen to treat as authoritative.
# ============================================================

class PushRejected(Exception):
    pass


def clone(remote: Repo) -> Repo:
    """git clone: copy all objects + refs into a brand new, fully independent repo."""
    local = Repo(name=f"{remote.name}-clone")
    local.store.merge_from(remote.store)
    local.refs = dict(remote.refs)
    for branch, h in remote.refs.items():
        local.remote_refs[f"origin/{branch}"] = h
    local.checkout("main")
    return local


def fetch(local: Repo, remote: Repo):
    """git fetch: download new objects, update remote-tracking refs (origin/*).
    Notice: this never touches local.refs — your own branches don't move."""
    local.store.merge_from(remote.store)
    for branch, h in remote.refs.items():
        local.remote_refs[f"origin/{branch}"] = h


def push(local: Repo, remote: Repo, branch: str, force=False):
    """
    git push: only succeeds if it's a fast-forward for the remote (i.e.
    the remote's current commit is an ancestor of what you're pushing) —
    otherwise it means you'd silently erase commits the remote has that
    you don't. force=True skips that check entirely (dangerous).
    """
    local_commit = local.refs[branch]
    remote_commit = remote.refs.get(branch)

    if remote_commit is not None and not force:
        if remote_commit not in local.ancestors(local_commit):
            raise PushRejected(
                f"rejected: remote has commit {remote_commit} you don't have locally. "
                f"fetch/merge (or rebase) first, or --force to overwrite."
            )

    remote.store.merge_from(local.store)
    remote.refs[branch] = local_commit
    local.remote_refs[f"origin/{branch}"] = local_commit
    return {"status": "forced" if force else "ok", "commit": local_commit}


def pull(local: Repo, remote: Repo, branch: str):
    """git pull = fetch + merge origin/<branch> into current branch."""
    fetch(local, remote)
    tracking_hash = local.remote_refs[f"origin/{branch}"]
    local.refs[f"__incoming_{branch}"] = tracking_hash
    result = merge(local, f"__incoming_{branch}")
    del local.refs[f"__incoming_{branch}"]
    return result


# ============================================================
# GUIDED TOUR — run this file to walk through every concept in order.
# Each section is self-contained; read the printed commentary as you go.
# ============================================================

def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


if __name__ == "__main__":

    # ---------- GROUP 1: object model, refs, three trees ----------
    section("GROUP 1 — content-addressing: same content = same hash")
    repo = Repo("demo")
    h1 = repo.store.store_blob("hello world")
    h2 = repo.store.store_blob("hello world")
    print(f"blob('hello world') twice -> {h1} == {h2}? {h1 == h2}")
    print("This is why identical files never take extra storage.")

    section("GROUP 1 — commit, and branches as pointers")
    repo.write_file("readme.md", "v1")
    repo.add("readme.md")
    c1 = repo.commit("initial commit")
    repo.write_file("readme.md", "v2")
    repo.add("readme.md")
    c2 = repo.commit("update readme")
    print(f"refs = {repo.refs}   <- 'main' is just a name pointing at {c2}")
    print("log:")
    for h, msg, parents in repo.log():
        print(f"  {h}  {msg}  parents={parents}")

    section("GROUP 1 — branching is instant (just a new pointer)")
    repo.branch("feature")
    repo.checkout("feature")
    print(f"refs after branching = {repo.refs}")
    print("Notice: no files were copied. Both names point at the same commit.")

    # ---------- GROUP 2: merge, rebase, cherry-pick ----------
    section("GROUP 2 — diverging history + a clean merge")
    repo.write_file("main.py", "print('feature work')")
    repo.add("main.py")
    c3 = repo.commit("add main.py on feature")

    repo.checkout("main")
    repo.write_file("readme.md", "v3 (edited on main)")
    repo.add("readme.md")
    c4 = repo.commit("edit readme on main")

    result = merge(repo, "feature")
    print(f"merge result: {result}")
    print("Files after merge:", repo.tree_of(repo.current_commit()))
    print("This is a real merge commit — it has TWO parents:")
    merged = repo.store.get(result["commit"])
    print(f"  parents = {merged['parents']}")

    section("GROUP 2 — a merge CONFLICT (both sides touch the same file differently)")
    repo2 = Repo("conflict-demo")
    repo2.write_file("shared.txt", "original")
    repo2.add("shared.txt")
    base = repo2.commit("base")
    repo2.branch("feature")

    repo2.write_file("shared.txt", "changed on main")
    repo2.add("shared.txt")
    repo2.commit("main's edit")

    repo2.checkout("feature")
    repo2.write_file("shared.txt", "changed on feature")
    repo2.add("shared.txt")
    repo2.commit("feature's edit")

    repo2.checkout("main")
    try:
        merge(repo2, "feature")
    except MergeConflict as e:
        print(f"Conflict raised, as expected: {e}")
        print("Real Git would insert <<<<<<< / ======= / >>>>>>> markers here")
        print("for you to resolve by hand, then `git add` + `git commit`.")

    section("GROUP 2 — rebase (replay commits, NEW hashes)")
    repo3 = Repo("rebase-demo")
    repo3.write_file("f.txt", "base")
    repo3.add("f.txt")
    b = repo3.commit("base commit")
    repo3.branch("feature")

    repo3.write_file("other.txt", "main work")
    repo3.add("other.txt")
    repo3.commit("main moves forward")

    repo3.checkout("feature")
    repo3.write_file("feature.txt", "feature work")
    repo3.add("feature.txt")
    old_feature_commit = repo3.commit("feature work")
    print(f"feature commit BEFORE rebase: {old_feature_commit}")

    new_tip = rebase(repo3, "main")
    print(f"feature commit AFTER rebase:  {new_tip}")
    print("Same content, DIFFERENT hash — because the parent changed.")
    print(f"Old commit still exists in the object store: {old_feature_commit in repo3.store.objects}")
    print(f"...but is it reachable from any ref now? {old_feature_commit in repo3.ancestors(repo3.refs['feature'])}")

    section("GROUP 2 — cherry-pick (replay ONE commit elsewhere)")
    repo4 = Repo("cherry-demo")
    repo4.write_file("f.txt", "base")
    repo4.add("f.txt")
    repo4.commit("base")
    repo4.branch("hotfix-source")
    repo4.checkout("hotfix-source")
    repo4.write_file("bugfix.txt", "the fix")
    repo4.add("bugfix.txt")
    fix_commit = repo4.commit("critical bugfix")

    repo4.checkout("main")
    repo4.write_file("unrelated.txt", "main kept moving separately")
    repo4.add("unrelated.txt")
    repo4.commit("unrelated main work")  # so main has genuinely diverged

    picked = cherry_pick(repo4, fix_commit)
    print(f"Original commit: {fix_commit}   Picked-onto-main commit: {picked}")
    print("Different hash despite same content, since the parent differs.")
    print(f"main now has: {repo4.tree_of(repo4.current_commit())}")

    # ---------- GROUP 4: undo + inspection ----------
    section("GROUP 4 — reset --hard vs revert")
    repo5 = Repo("undo-demo")
    repo5.write_file("f.txt", "v1")
    repo5.add("f.txt")
    r_c1 = repo5.commit("v1")
    repo5.write_file("f.txt", "v2 (mistake)")
    repo5.add("f.txt")
    r_c2 = repo5.commit("oops, bad commit")

    print(f"Before undo: {repo5.tree_of(repo5.current_commit())}")
    reset(repo5, r_c1, mode="hard")
    print(f"After reset --hard to {r_c1}: {repo5.tree_of(repo5.current_commit())}")
    print(f"refs = {repo5.refs}  (branch pointer moved BACKWARD)")
    print(f"Is the 'mistake' commit dangling now? {r_c2 in dangling_commits(repo5)}")
    print("It's still in the object store — recoverable via reflog — until gc runs:")
    for entry in repo5.reflog:
        print(f"  reflog: {entry}")

    section("GROUP 4 — revert (safe on shared branches: adds, never erases)")
    repo6 = Repo("revert-demo")
    repo6.write_file("f.txt", "v1")
    repo6.add("f.txt")
    repo6.commit("v1")
    repo6.write_file("f.txt", "v2 (mistake)")
    repo6.add("f.txt")
    mistake = repo6.commit("oops, bad commit")
    revert(repo6, mistake)
    print(f"After revert: {repo6.tree_of(repo6.current_commit())}")
    print("History GREW (3 commits) instead of being rewritten — safe even if")
    print("someone else already has the 'mistake' commit.")
    for h, msg, parents in repo6.log():
        print(f"  {h}  {msg}")

    # ---------- GROUP 3: remotes ----------
    section("GROUP 3 — clone, fetch, and a rejected push")
    origin = Repo("origin")
    origin.write_file("f.txt", "v1")
    origin.add("f.txt")
    origin.commit("initial")

    dev_a = clone(origin)
    dev_b = clone(origin)
    print(f"dev_a and dev_b both cloned origin at commit {origin.refs['main']}")

    dev_a.write_file("f.txt", "v2 from dev_a")
    dev_a.add("f.txt")
    dev_a.commit("dev_a's change")
    push(dev_a, origin, "main")
    print(f"dev_a pushed. origin main is now {origin.refs['main']}")

    dev_b.write_file("g.txt", "dev_b's new file")
    dev_b.add("g.txt")
    dev_b.commit("dev_b's change (based on stale origin)")
    try:
        push(dev_b, origin, "main")
    except PushRejected as e:
        print(f"dev_b's push REJECTED: {e}")
        print("This is the non-fast-forward safety check — it stops dev_b from")
        print("silently erasing dev_a's already-pushed commit.")

    section("GROUP 3 — the fix: pull (fetch + merge), then push cleanly")
    pull_result = pull(dev_b, origin, "main")
    print(f"pull result: {pull_result}")
    push(dev_b, origin, "main")
    print(f"push succeeded now. origin main = {origin.refs['main']}")
    print(f"Final files on origin: {origin.tree_of(origin.refs['main'])}")

    section("Tour complete")
    print("Re-read README.md alongside this output to connect each demo")
    print("back to the problem it was built to solve.")