import os


def dir_is_empty(path):
    return next(os.scandir(path), None) is None
