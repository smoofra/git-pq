#!/usr/bin/env python3

from setuptools import setup, find_packages

with open('README.md') as readme_file:
    readme = readme_file.read()

requirements = ["pyyaml", "gitpython"]

setup(
    author="Lawrence D'Anna",
    python_requires='>=3.5',
    description="a cross between quilt and git-subtree",
    entry_points={
        'console_scripts': [
            'git-pq=gitpq:main',
        ],
    },
    install_requires=requirements,
    long_description=readme,
    long_description_content_type='text/markdown',
    include_package_data=True,
    name='git-pq',
    py_modules=['gitpq'],
    version='0.9.1',
)
