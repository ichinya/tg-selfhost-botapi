# Synthetic apk refresh fixture

All sources are authored in this repository under the MIT license. There is no
vendor code or claim about an actual CVE. Versions 1 and 2 differ only in the
integer returned by the same ABI, selected by the APKBUILD compiler macro.
SHA256SUMS seals the source, consumer, license and packaging recipe. The explicit
runner validates it before packaging. RSA signing keys are generated in a temporary
directory for each integration invocation and never used in production images.
