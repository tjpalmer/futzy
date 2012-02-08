#!/usr/bin/env python

"""
A node to kick off rcssserver, the 2D RoboCup Soccer Server.

TODO Should the monitor be linked to this or separate. If separate, this node
TODO really does exist just to kick off (and maintain?) the server.
"""


def _configure():
    from roslib import load_manifest
    load_manifest('futzy')


def find_server_exe():
    from os import listdir
    from os.path import abspath, dirname, isfile, join
    # Look for rcssserver dir through parent dirs of where we start.
    # TODO Also look in system PATH.
    server_dir_name = 'rcssserver'
    server_dir = None
    current = abspath(dirname(__file__))
    while True:
        kids = listdir(current)
        if server_dir_name in kids:
            server_dir = join(current, server_dir_name)
            break
        parent = abspath(join(current, '..'))
        if parent == current:
            # Must be at root.
            break
        # Go into the parent.
        current = parent
    if server_dir:
        # Find the exe. TODO Support Windows conventions.
        # Meanwhile, on Linux, the exe matches exactly the dir name.
        exe = join(server_dir, 'src', 'rcssserver')
        if not isfile(exe):
            exe = None
    else:
        exe = None
    return exe


def main():
    from rospy import is_shutdown
    from subprocess import Popen
    exe = find_server_exe()
    print exe
    process = Popen(exe)
    while not is_shutdown():
        pass
    # Seems TERM is good enough.
    process.terminate()


_configure()
if __name__ == '__main__':
    main()
