# This file is part of gilmsg.
# Copyright (C) 2015 Red Hat, Inc.
#
# gilmsg is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# gilmsg is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with gilmsg; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 0.1.2.15.0 USA
#
# Authors:  Ralph Bean <rbean@redhat.com>
#

try:
    from setuptools import setup
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup

f = open('README.rst')
long_description = f.read().strip()
long_description = long_description.split('split here', 1)[-1]
f.close()


install_requires = [
    'fedmsg',
    'fedmsg[crypto]',
    'fedmsg[consumers]',
    'fedmsg[commands]',
]

setup(
    name='gilmsg',
    version='0.1.2',
    description="A reliability layer on top of fedmsg",
    long_description=long_description,
    author='Ralph Bean',
    author_email='rbean@redhat.com',
    url='https://github.com/fedora-infra/gilmsg/',
    license='LGPLv2+',
    install_requires=install_requires,
    py_modules=['gilmsg'],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            "gilmsg-logger=gilmsg:logger_cli",
        ],
    },
)
