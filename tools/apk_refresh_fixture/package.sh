#!/bin/sh
set -eu
: "${HOST_UID:?HOST_UID is required}" "${HOST_GID:?HOST_GID is required}"
cleanup() {
    status=$?
    trap - EXIT
    if ! chown -R "$HOST_UID:$HOST_GID" /work; then
        echo "Failed to restore /work ownership" >&2
        [ "$status" -ne 0 ] || status=1
    fi
    exit "$status"
}
trap cleanup EXIT
apk add --no-cache alpine-sdk openssl
openssl genrsa -out /work/issue23.rsa 2048
openssl rsa -in /work/issue23.rsa -pubout -out /work/issue23.rsa.pub
cp /work/issue23.rsa.pub /etc/apk/keys/issue23.rsa.pub
export PACKAGER_PRIVKEY=/work/issue23.rsa
export PACKAGER='Issue 23 synthetic fixture'
for version in 1 2; do
    mkdir -p /work/issue23/v$version
    cd /work/issue23/v$version
    cp /work/source/fixture.c /work/source/LICENSE .
    sed "s/@VERSION@/$version/g" /work/source/APKBUILD.in > APKBUILD
    abuild -F checksum
    abuild -F -r -P /work/packages
    mkdir -p /work/repo-v$version/x86_64
    cp /work/packages/issue23/x86_64/issue23-fixture-$version-r0.apk /work/repo-v$version/x86_64/
    apk index -o /work/repo-v$version/x86_64/APKINDEX.tar.gz /work/repo-v$version/x86_64/*.apk
    abuild-sign -k /work/issue23.rsa /work/repo-v$version/x86_64/APKINDEX.tar.gz
done
