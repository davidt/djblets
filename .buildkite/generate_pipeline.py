#!/usr/bin/env python3
"""Generate Buildkite pipeline steps from tox environments."""

from __future__ import annotations

import json
import re
import subprocess
import sys


ATTESTATION_FILE = 'build.attestation.json'
DOCKER_PLUGIN = 'docker#v5.13.0'
PACKAGES_ORG = 'david-trowbridge'
PACKAGES_REGISTRY = 'python'

PACKAGE_SECRET = 'PACKAGE_REGISTRY_TOKEN'

INSTALL_SYSTEM_DEPS_CMD = (
    'export DEBIAN_FRONTEND=noninteractive'
    ' && apt-get update -qq'
    ' && apt-get install -yqq nodejs npm tzdata'
)

SETUP_PIP_INDEX_CMD = (
    'export PIP_EXTRA_INDEX_URL="https://buildkite:$${PACKAGE_REGISTRY_TOKEN}'
    f'@packages.buildkite.com/{PACKAGES_ORG}/{PACKAGES_REGISTRY}'
    '/pypi/simple"'
)


def main() -> None:
    """Generate the new pipeline."""
    result = subprocess.run(
        ['tox', '-l'],
        capture_output=True,
        text=True,
        check=True,
    )

    pythons: list[str] = []

    for env in result.stdout.strip().split('\n'):
        match = re.match(r'py(\d)(\d+)$', env)
        if not match:
            print(f'Skipping unrecognized env: {env}', file=sys.stderr)
            continue

        pythons.append(f'{match.group(1)}.{match.group(2)}')

    pythons.sort()

    steps: list[object] = [
        {
            'group': ':pytest: Tests',
            'key': 'tests',
            'steps': [{
                'label': ':pytest: Py {{matrix.python}}',
                'command': '\n'.join([
                    INSTALL_SYSTEM_DEPS_CMD,
                    SETUP_PIP_INDEX_CMD,
                    'pip install --upgrade pip',
                    'pip install tox',
                    "tox -e \"py$(printf '%s' '{{matrix.python}}'"
                    " | tr -d .)\"",
                ]),
                'secrets': [PACKAGE_SECRET],
                'matrix': {
                    'setup': {
                        'python': pythons,
                    },
                },
                'plugins': [{
                    DOCKER_PLUGIN: {
                        'image': 'python:{{matrix.python}}',
                        'environment': [
                            PACKAGE_SECRET,
                        ],
                    },
                }],
            }],
        },
        {
            'label': ':package: Build wheel',
            'key': 'build-wheel',
            'depends_on': 'tests',
            'command': '\n'.join([
                INSTALL_SYSTEM_DEPS_CMD,
                SETUP_PIP_INDEX_CMD,
                'pip install --upgrade pip',
                'pip install build',
                'python -m build --wheel',
            ]),
            'secrets': [PACKAGE_SECRET],
            'artifact_paths': 'dist/*.whl',
            'plugins': [
                {
                    DOCKER_PLUGIN: {
                        'image': 'python:3.10',
                        'environment': [
                            PACKAGE_SECRET,
                        ],
                    },
                    'generate-provenance-attestation#v1.0.0': {
                        'artifacts': '*.whl',
                        'attestation_name': ATTESTATION_FILE,
                    },
                },
            ],
        },
        {
            'label': ':wastebasket: Delete existing dev package',
            'key': 'delete-old-package',
            'depends_on': 'build-wheel',
            'plugins': [{
                'https://github.com/davidt/package-delete-buildkite-plugin.git': {
                    'artifacts': '*.whl',
                    'registry': 'david-trowbridge/python',
                },
            }],
        },
        {
            'label': ':buildkite: Publish package',
            'depends_on': 'delete-old-package',
            'plugins': [{
                'publish-to-packages#v2.2.0': {
                    'artifacts': '*.whl',
                    'registry': 'david-trowbridge/python',
                    'attestations': ATTESTATION_FILE,
                },
            }],
        },
    ]

    json.dump({'steps': steps}, sys.stdout, indent=2)


if __name__ == '__main__':
    main()
