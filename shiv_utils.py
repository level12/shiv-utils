import hashlib
import logging
import os
import pathlib
import subprocess
import shutil
import sys

log = logging.getLogger(__name__)

SHIV_STDERR_DEBUG = 'SHIV_STDERR_DEBUG' in os.environ


def log_debug(msg):
    """ Log to stderr based on environment variable

        The preamble will usually get called so early in the process setup that nothing else will
        have had a chance to run yet, not even code that sets up Python logging.  This permits
        logging to stderr if the environment variable SHIV_STDERR_DEBUG has been set.

        But, we also pass the value on to the Python logging library in case the normal logging
        faculties have been used.
    """
    log.debug(msg)
    if SHIV_STDERR_DEBUG:
        print(msg, file=sys.stderr)


def cleanup_shivs(env, site_packages_dpath):
    cache_dpath = site_packages_dpath.parent
    build_id = env.build_id

    dname_prefix = cache_dpath.name[0:-64]
    dname_length = len(cache_dpath.name)
    cache_root_dpath = cache_dpath.parent

    for dpath in cache_root_dpath.iterdir():
        dir_name = dpath.name

        if build_id in dir_name \
                or len(dir_name) != dname_length \
                or dir_name[0:-64] != dname_prefix \
                or not dpath.is_dir():
            continue

        log_debug(f'Deleting {dpath} and lock file')
        shutil.rmtree(dpath)

        lock_fpath = pathlib.Path(cache_root_dpath, f'.{dpath.stem}_lock')

        if lock_fpath.exists():
            # Don't use missing_ok param to unlink b/c it's Python 3.8 only
            lock_fpath.unlink()


def sub_run(*args, **kwargs):
    kwargs['check'] = True
    return subprocess.run(args, **kwargs)


def fpath_read(from_fpath):
    if not from_fpath.exists():
        return

    return from_fpath.read_text().strip()


def sha256sum(src_fpath, save_to=None):
    with open(src_fpath, 'rb') as f:
        bytes = f.read() # read entire file as bytes
        hash = hashlib.sha256(bytes).hexdigest()

    if not save_to:
        return hash

    save_to.write_text(hash)


def build(pkg_dpath, reqs_rel_fpath, app_dname, entry_point, pybin='python3',
        pyz_fpath=None, preamble_fpath=None, force_deps=False):
    app_dpath = pkg_dpath / app_dname
    dist_dpath = pkg_dpath / '_shiv_dist'
    dist_app_dpath = dist_dpath / app_dname
    reqs_fpath = pkg_dpath / reqs_rel_fpath
    pyz_fpath = pyz_fpath or pkg_dpath.joinpath(f'{app_dname}.pyz')
    reqs_hash_fpath = dist_dpath / '_shiv_reqs_hash.txt'

    install_deps = force_deps or fpath_read(reqs_hash_fpath) != sha256sum(reqs_fpath)

    if install_deps:
        # cleanup all present dependency files to avoid accidental junk in the build
        if dist_dpath.exists():
            shutil.rmtree(dist_dpath)

        # install dependencies
        sub_run(pybin, '-m', 'pip', 'install', '-r', reqs_fpath, '--target', dist_dpath)
        sha256sum(reqs_fpath, reqs_hash_fpath)
    else:
        print('Requirements already up-to-date, skipping install.')
        if dist_app_dpath.exists():
            # only remove the app's files so they can be replaced
            shutil.rmtree(dist_app_dpath)

    shutil.copytree(app_dpath, dist_app_dpath, dirs_exist_ok=True)

    shiv_args = [
        'shiv',
        '--compile-pyc',
        '--compressed',
        '--site-packages', dist_dpath,
        '--python', f'/usr/bin/env {pybin}',
        '--output-file', pyz_fpath,
        '--entry-point', entry_point,
    ]

    if preamble_fpath:
        shiv_args.extend(['--preamble', preamble_fpath])

    sub_run(*shiv_args)

    _cwd = pathlib.Path.cwd()
    if pyz_fpath.is_relative_to(_cwd):
        _pyz_fpath = pyz_fpath.relative_to(_cwd)
    else:
        _pyz_fpath = pyz_fpath

    print(f'Shiv bin saved as: ./{_pyz_fpath}')
