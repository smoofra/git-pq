git-pq
======

Introduction
------------

`git-pq` is a yet another tool for including one git repo as a subdirectory
of another, like `git-submodule` or `git-subtree`.

At the same time it is a tool for maintaining a patch queue, like `quilt` or `stg`
(Stacked Git).

It is like `git-subtree`, in that the contents of the sub-repository is included directly
as an ordinary git-tracked subdirectory in the contents of the super-repository.   Users that just
want to check out the code and build it do not even need to know this tool exists.

`git-pq` is like `quilt` or `stg` in that it supports a workflow based around a patch queue,
rather than a workflow based on merges.   Unlike `quilt` or `stg`, there are no new
commands for manipulating the patch queue.    Instead, you use ordinary git commands:  `git commit`
to add a patch,  `git rebase -i` to reorder or combine patches, etc.

`git-pq` stores the patch queue for each subdirectory as a simple directory full of patch files,
which are also tracked by git as ordinary files.


Synopsis
--------

```
$ git fetch https://github.com/python/cpython.git v3.8.2
$ git tag python-3.8.2 FETCH_HEAD
$ git pq init --base python-3.8.2 --patches patches python
$ git commit

$ git pq edit Python
$ echo "This is a patched version of python" >>Python/README.rst
$ git -C Python commit -a -m 'edited README'

$ git pq refresh Python
$ cat patches/0001-edited-README.patch

diff --git a/README.rst b/README.rst
--- a/README.rst
+++ b/README.rst
@@ -263,3 +263,4 @@ so it may be used in proprietary projects.  There are interfaces to some GNU
code but these are entirely optional.

All trademarks referenced herein are property of their respective holders.
+This is a patched version of python

$ git add ./patches ./Python
$ git commit -m 'added the first patch to the queue'
```

Description
-----------

`git-pq` is built on `git-worktree`.   You should read the documentation for that
command before continuing to read this.

The main idea of `git-pq` is that it is possible to create *overlapping* git worktrees.

In the example above the command `git pq edit Python` does two things.

* It creates a new branch called `pq-Python`, which is the result of applying `patches/*.patch` to the tag `python-3.8.2`
* It creates a new worktree rooted at `./Python`, (inside the current worktree!) with branch `pq-Python`

To edit the patchquee, you simple cd into `./Python` and add or remove commits to the `pq-Python` branch using
ordinary git commands.

Then, when you are satisfied with the branch, use `git pq refresh` to update the patch files, and commit both
the patch files and the changes made to the subtree to the main branch.

Files
-----

Each subtree tracked by this tool is recorded in a yaml file at the root of the repo file called `./.git-pq`.

```
subtrees:
    - base: python-3.8.2
      patches_path: patches
      path: Python
```

Subcommands
-----------

### `git pq status`

List the subtrees managed by `git-pq` and their current status.

### `git pq edit SUBTREE`

Prepare to edit a subtree by making a patchqueue branch and worktree for it.

### `git pq finish SUBTREE`

Remove the worktree and delete the branch created by the edit subcommand.

### `git pq refresh SUBTREE`

Re-create the patches for a subtree based on the changes made to that subtree's branch.

### `git pq verify SUBTREE`

Verify that the patches applied to the base match the content of the subtree.

### `git pq init --base BASE --patches PATCHES SUBTREE`

Create a new subtree at SUBTREE, based on the tag BASE, with patches directory PATCHES.
This will modify `.git-pq`,  and also `git add .git-pq` if it has not yet been added to
your repository.
