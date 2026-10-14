#!/usr/bin/env bash
# One-time: create a self-signed "SAbi Local Signing" certificate in the login keychain so local
# builds keep a stable signature (and their macOS permissions) across rebuilds. Free, local only.
set -euo pipefail
name="SAbi Local Signing"
if security find-identity -p codesigning | grep -q "\"$name\""; then
  echo "\"$name\" already exists."
  exit 0
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/cs.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $name
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -keyout "$tmp/key.pem" -out "$tmp/cert.pem" -days 3650 -config "$tmp/cs.cnf"
/usr/bin/openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -out "$tmp/id.p12" -passout pass:tmp -name "$name"
security import "$tmp/id.p12" -k ~/Library/Keychains/login.keychain-db -P tmp -T /usr/bin/codesign
echo "Allow codesign to use the key (asks for your login password):"
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -l "$name" ~/Library/Keychains/login.keychain-db >/dev/null
echo "Created \"$name\"."
