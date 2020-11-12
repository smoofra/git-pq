#!/usr/bin/env python3

import argparse
import os
import glob
import sys
from collections import namedtuple, defaultdict
import shutil
from contextlib import contextmanager
import re

import yaml
import git   #gitpython

def relpath_nodots(path, start):
    ret = os.path.relpath(path, start)
    if any(x == '.' or x == '..' for x in ret.split(os.path.sep)):
        raise OSError("relative path has dots in it")
    return ret

def print_table(rows, out=sys.stdout):
    widths = defaultdict(int)
    for row in rows:
        for i,cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    for row in rows:
        for i,cell in enumerate(row):
            out.write(str(cell).ljust(widths[i]+2))
        out.write("\n")


@contextmanager
def TablePrinter(out=sys.stdout):
    rows = list()
    def printrow(*row):
        rows.append(row)
    yield printrow
    print_table(rows, out)



class Worktree(dict):
    """Represents one record output by `git worktree list`"""

    @property
    def branch(self):
        return self['branch']

    @property
    def worktree(self):
        return self['worktree']

    @property
    def HEAD(self):
        return self['HEAD']


class Subtree:
    """Represents a configured git-pq subtree"""

    def __init__(self, repo : git.Repo, config):
        if os.path.isabs(config['path']):
            raise ValueError
        self.relpath = config['path']
        self.path = os.path.join(repo.working_dir, config['path'])
        self.patches_path = os.path.join(repo.working_dir, config['patches_path'])
        self.base = config['base']
        self.name = os.path.basename(self.path)
        self.worktree = repo.get_worktree(self.path)

    @property
    def uipath(self):
        try:
            if os.path.samefile(self.path, self.relpath):
                return self.relpath
        except OSError:
            pass
        return self.path


class Repo(git.Repo):

    def worktrees(self):
        out = self.git.worktree('list', '--porcelain')
        for stanza in out.split('\n\n'):
            def pairs():
                for line in stanza.strip().split("\n"):
                    if line.strip() == 'detached':
                        yield ['branch', None]
                    else:
                        yield line.split(" ", 1)
            yield Worktree(pairs())

    def main_worktree(self):
        return next(self.worktrees())['worktree']

    def get_worktree(self, path):
        if not os.path.exists(path):
            return False
        for worktree in self.worktrees():
            wtpath = worktree['worktree']
            if os.path.exists(wtpath) and os.path.samefile(path, wtpath):
                return worktree
        return None

    def is_worktree(self, path):
        return self.get_worktree(path) is not None

    def iter_patches(self, patchdir):
        return sorted(glob.glob(os.path.join(os.path.abspath(patchdir), "*.patch")))

    def apply_patches_keep_tree(self, patchdir, base, name):
        restype = namedtuple('AppliedPatches', ['worktree', 'branch', 'git_dir'])

        temp = os.path.join(self.git_dir, 'pq', 'temp-' + name)
        temp_branch = 'pq-' + name
        if os.path.exists(temp):
            raise Exception(f"{temp} already exists")
        try:
            self.git.worktree('add', '-b', temp_branch, temp, base)
            temp_repo = Repo(temp)
            patches = list(self.iter_patches(patchdir))
            if patches:
                temp_repo.git.am('--whitespace=nowarn', '--quiet', *patches)
            return restype(temp, temp_branch, temp_repo.git_dir)
        except:
            if os.path.exists(temp):
                self.git.worktree('remove', '--force', temp)
                self.git.branch('-D', temp_branch)
            raise

    def apply_patches(self, patchdir, base):
        worktree = None
        try:
            worktree, branch, git_dir = self.apply_patches_keep_tree(patchdir, base, 'temp')
            return self.git.rev_parse('--short', branch)
        finally:
            if worktree:
                self.git.worktree('remove', '--force', worktree)
                self.git.branch('-D', branch)

    def edit_pq(self, subtree):
        if subtree.worktree:
            raise Exception(f"{subtree.path} is already a worktree")
        if os.path.exists(os.path.join(self.git_dir, 'commondir')):
            raise Exception(f"{self.git_dir} is not the primary GIT_DIR")

        wt = None
        dot_git_file = os.path.join(subtree.path, ".git")
        try:
            wt = self.apply_patches_keep_tree(subtree.patches_path, subtree.base, subtree.name)
            with open(os.path.join(wt.git_dir, 'gitdir'), 'w') as f:
                f.write(os.path.join(subtree.path, ".git"))
                f.write("\n")
            with open(dot_git_file, 'w') as f:
                f.write(f"gitdir: {wt.git_dir}\n")
        except:
            if os.path.exists(dot_git_file):
                os.unlink(dot_git_file)
            if wt:
                shutil.rmtree(wt.git_dir)
                self.git.branch('-D', wt.branch)
            raise
        finally:
            if wt:
                shutil.rmtree(wt.worktree)

    def finish_pq(self, subtree, out=sys.stdout):
        if not subtree.worktree:
            print(f"{subtree.uiname} is not being edited")
            return
        wt = Repo(subtree.path)
        ok = True
        try:
            relpath = relpath_nodots(wt.git_dir, self.git_dir)
        except OSError:
            ok = False
        relpath = relpath.split(os.path.sep)
        ok = ok and len(relpath) > 1 and relpath[0] == 'worktrees'
        if not ok:
            print(f"the GIT_DIR for {subtree.uiname} is unexpectedly at {wt.git_dir}, cannot proceed")
            return
        os.unlink(os.path.join(subtree.path, '.git'))
        shutil.rmtree(wt.git_dir)
        self.delete_head(git.Reference(self, subtree.worktree.branch), force=True)

    pq_config_file_basename = '.git-pq'

    @property
    def pq_config_file(self):
        return os.path.join(self.working_dir,  self.pq_config_file_basename)

    def read_pq_config(self):
        if os.path.exists(self.pq_config_file):
            with open(self.pq_config_file, 'r') as f:
                config = yaml.load(f, Loader=yaml.SafeLoader)
        else:
            config = dict()
        return config

    def write_pq_config(self, config):
        with open(self.pq_config_file, 'w') as f:
            yaml.dump(config, f)

    def get_pq_subtrees(self):
        config = self.read_pq_config()
        for subtree in config['subtrees']:
            yield Subtree(self, subtree)
            
    def get_pq_subtree(self, path):
        if not os.path.exists(path):
            raise OSError(f"{path} does not exist")
        for subtree in self.get_pq_subtrees():
            if os.path.exists(subtree.path) and os.path.samefile(subtree.path, path):
                return subtree
        raise OSError(f"{path} is not a a git-pq subtree")

    def print_pq_status(self, out=sys.stdout):
        with TablePrinter(out=out) as printrow:
            for subtree in self.get_pq_subtrees():
                if subtree.worktree:
                    branch_name = git.Reference(self, subtree.worktree.branch).name
                    printrow(subtree.relpath, f"[editing: {branch_name}]")
                else:
                    printrow(subtree.relpath, "[not editing]")
        out.write("\n")

    def refresh_pq(self, subtree):
        if not subtree.worktree:
            print (f"subtree {subtree.relpath} is not being edited")
            return
        for patch in glob.glob(os.path.join(subtree.patches_path, "*.patch")):
            os.unlink(patch)
        self.git.format_patch('--no-numbered', '-o', subtree.patches_path, '^'+subtree.base, subtree.worktree.branch)

        for patch in glob.glob(os.path.join(subtree.patches_path, "*.patch")):
            with open (patch, "r+") as f:
                lines = f.readlines()
                f.truncate(0)
                f.seek(0)
                while lines[-1].rstrip() == '':
                    lines.pop()
                if lines[-2].rstrip() == '--' and re.match('\d+\.\d+', lines[-1]):
                    lines.pop()
                    lines.pop()
                for line in lines:
                    assert line.endswith('\n')
                    if not any(line.startswith(x) for x in ('index ', 'From ', 'Message-Id: ', 'In-Reply-To: ', 'References: ')):
                        f.write(line)

    def verify_pq(self, subtree, out=sys.stdout):
        ok = True
        def pr(*args):
            print(*args, file=out)
            nonlocal ok
            ok = False
        if self.index.diff(None, paths=subtree.path):
            pr(f"There are unstaged changes at {subtree.uipath}")
        if self.index.diff('HEAD', paths=subtree.path):
            pr(f"There are changes staged for commit at {subtree.uipath}")
        if subtree.worktree:
            wt = Repo(subtree.path)
            if wt.index.diff(None):
                pr(f"There are unstaged changes (in the worktree) at {subtree.uipath}")
            if wt.index.diff('HEAD'):
                pr(f'There are changes staged (in the worktree) at {subtree.uipath}')
        for patch in self.iter_patches(subtree.patches_path):
            patch = relpath_nodots(patch, self.working_dir)
            if (patch,0) not in self.index.entries:
                pr("patch not added to index:", patch)
        applied = self.apply_patches(subtree.patches_path, subtree.base)
        if self.rev_parse("HEAD:"+subtree.relpath).diff(applied):
            pr(f"❌ Subtree at {subtree.uipath} does not match patches")
            pr(f"to see: git diff {applied} HEAD:{subtree.relpath}")
        elif ok:
            pr(f"✅ Subtree at {subtree.uipath} looks good")
        else:
            pr(f"✓ Patches match HEAD:{subtree.relpath}, but worktree or index is dirty.")


    def init_pq(self, path, patches, base, out=sys.stdout):
        if os.path.exists(path):
            print(f"{path} already exists")
            return
        path = relpath_nodots(path, start=self.working_dir)
        patches = relpath_nodots(patches, start=self.working_dir)

        self.git.read_tree('--prefix='+path, base)
        self.git.checkout('--', os.path.join(self.working_dir, path))

        config = self.read_pq_config()
        if not 'subtrees' in config:
            config['subtrees'] = list()
        config['subtrees'].append({
            'path': path,
            'patches_path': patches,
            'base': base
        })
        self.write_pq_config(config)
        if not (self.pq_config_file_basename,0) in self.index.entries:
            self.git.add(self.pq_config_file)



def main():

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True) # this line changed

    subparsers.add_parser('status', help="show current status of git-pq enabled subtrees")

    edit_parser = subparsers.add_parser('edit', help="Make a subtree editable using git-worktree")
    edit_parser.add_argument('subtree')

    finish_parser = subparsers.add_parser("finish", help="undo 'git pq edit' by turning a subtree back into a normal directory")
    finish_parser.add_argument('subtree')

    refresh_parser = subparsers.add_parser('refresh', help="Refresh the patches of a subtree from its git branch")
    refresh_parser.add_argument('subtree')

    verify_parser = subparsers.add_parser('verify', help="verify that a subtree matches its patch directory")
    verify_parser.add_argument('subtree')

    init_parser = subparsers.add_parser("init", help="add a new subtree")
    init_parser.add_argument("--base", "-b", required=True)
    init_parser.add_argument("--patches", "-p", required=True)
    init_parser.add_argument('subtree')

    args = parser.parse_args()

    repo = Repo(search_parent_directories=True)

    if args.command == 'status':
        repo.print_pq_status()

    if hasattr(args, 'subtree') and args.command != 'init':
        subtree = repo.get_pq_subtree(args.subtree)

    if args.command == 'refresh':
        repo.refresh_pq(subtree)

    if args.command == 'verify':
        repo.verify_pq(subtree)

    if args.command == 'edit':
        repo.edit_pq(subtree)

    if args.command == 'finish':
        repo.finish_pq(subtree)

    if args.command == 'init':
        repo.init_pq(args.subtree, args.patches, args.base)

if __name__ == "__main__":
    main()