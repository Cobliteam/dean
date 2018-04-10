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
        'pyyaml',

    ],
    entry_points={
        'console_scripts': ['dean=dean.main:main']
    },
    keywords='documentation git')
