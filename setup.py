from setuptools import setup

VERSION = '0.1.0'

setup(
    name='dean',
    packages=['dean'],
    version=VERSION,
    description='Build and aggregate documentation for multiple Git repositories',
    long_description=open('README.md').read(),
    url='https://github.com/Cobliteam/dean',
    download_url='https://github.com/Cobliteam/dean/archive/{}.tar.gz'.format(VERSION),
    author='Daniel Miranda',
    author_email='daniel@cobli.co',
    license='MIT',
    install_requires=[
        'GitPython',
        'click',
        'pyyaml',
        'aiofiles',
        'dataclasses; python_version < "3.7"'
    ],
    entry_points={
        'console_scripts': ['dean=dean.cli:main']
    },
    keywords='documentation git')
