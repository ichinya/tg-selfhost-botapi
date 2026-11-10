#!/bin/sh
set -eu
apk add --no-cache alpine-sdk openssl
openssl genrsa -out /work/issue23.rsa 2048
openssl rsa -in /work/issue23.rsa -pubout -out /work/issue23.rsa.pub
export PACKAGER_PRIVKEY=/work/issue23.rsa
export PACKAGER='Issue 23 synthetic fixture'
for version in 1 2; do
    mkdir -p /work/issue23/v$version
    cd /work/issue23/v$version
    cp /work/source/fixture.c /work/source/LICENSE .
    sed "s/@VERSION@/$version/g" /work/source/APKBUILD.in > APKBUILD
    abuild -F checksum
    abuild -F -r -P /work/packages
    mkdir -p /work/repo-v$version
    cp /work/packages/issue23/x86_64/issue23-fixture-$version-r0.apk /work/repo-v$version/
    apk index -o /work/repo-v$version/APKINDEX.tar.gz /work/repo-v$version/*.apk
    abuild-sign -k /work/issue23.rsa /work/repo-v$version/APKINDEX.tar.gz
done
chmod -R a+rwX /work
