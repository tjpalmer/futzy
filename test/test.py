#!/usr/bin/env python


def _configure():
    from os.path import abspath, dirname, join
    from sys import path
    futzy_path = abspath(join(dirname(__file__), '..', 'src'))
    if futzy_path not in path:
        path.append(futzy_path)


def main():
    from futzy import PlayerClient
    with PlayerClient(team = 'test') as player:
        raw_input()
    #raw_input()


_configure()
if __name__ == '__main__':
    main()
