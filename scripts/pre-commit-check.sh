#!/bin/sh

set -eu

manifest_version() {
    sed -n -e 's/^.*"version": "\([0-9\.]\+\)".*$/\1/p' custom_components/smartbox/manifest.json
}

changelog_version() {
    sed -n -e 's/^.*## \([0-9\.]\+\).*$/\1/p' CHANGELOG.md | head -1
}

manifest_smartbox_version() {
    sed -n -e 's/^.*\(smartbox.git@v[0-9\.]\+\).*$/\1/p' custom_components/smartbox/manifest.json
}

requirements_smartbox_version() {
    sed -n -e 's/^.*\(smartbox.git@v[0-9\.]\+\).*$/\1/p' requirements.txt
}

if [ $(manifest_version) != $(changelog_version) ]
then
    echo "Manifest version $(manifest_version) does not match changelog $(changelog_version)" >&2
    exit 1
fi

if [ $(manifest_smartbox_version) != $(requirements_smartbox_version) ]
then
    echo "Manifest smartbox version $(manifest_smartbox_version) does not match requirements smartbox version $(requirements_smartbox_version)" >&2
    exit 1
fi

black --check .
