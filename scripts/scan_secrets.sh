#!/usr/bin/env bash
# Escaneo rapido de patrones de credenciales antes de cada commit.
# Uso: bash scripts/scan_secrets.sh
# Sale con codigo != 0 y lista de coincidencias si encuentra algo sospechoso.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Patrones de credenciales/tokens que nunca deben quedar en el repo
PATTERNS=(
  'AKIA[0-9A-Z]{16}'                 # Access Key ID de AWS
  'ASIA[0-9A-Z]{16}'                 # Access Key ID temporal (sesion)
  'aws_secret_access_key\s*=\s*\S+'
  'aws_session_token\s*=\s*\S+'
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  'password\s*=\s*["\047][^"\047]+["\047]'
  'passwd\s*=\s*["\047][^"\047]+["\047]'
)

# Archivos/carpetas que no se escanean (binarios, dependencias, estado de terraform ya ignorado,
# y este mismo script porque contiene los patrones como texto literal)
EXCLUDE_DIRS='--glob=!.git/* --glob=!.venv/* --glob=!venv/* --glob=!node_modules/* --glob=!*.tfstate --glob=!*.tfstate.* --glob=!scripts/scan_secrets.sh --glob=!CLAUDE.md --glob=!**/global-bundle.pem'

FOUND=0

for pattern in "${PATTERNS[@]}"; do
  if command -v rg >/dev/null 2>&1; then
    matches=$(rg -n --no-heading -i -e "$pattern" $EXCLUDE_DIRS . 2>/dev/null)
  else
    matches=$(grep -RnoiE "$pattern" \
      --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=node_modules \
      --exclude=scan_secrets.sh --exclude=CLAUDE.md --exclude=global-bundle.pem \
      . 2>/dev/null)
  fi

  if [ -n "$matches" ]; then
    echo "!! Posible secreto encontrado (patron: $pattern):"
    echo "$matches"
    echo "---"
    FOUND=1
  fi
done

# Archivos que jamas deben estar rastreados por git
FORBIDDEN_FILES=$(git ls-files | grep -E '\.(pem|key|tfstate|tfvars)$|^\.env$' || true)
if [ -n "$FORBIDDEN_FILES" ]; then
  echo "!! Archivos prohibidos rastreados por git:"
  echo "$FORBIDDEN_FILES"
  FOUND=1
fi

if [ "$FOUND" -ne 0 ]; then
  echo ""
  echo "scan_secrets.sh: SE ENCONTRARON POSIBLES SECRETOS. Revisa y limpia antes de hacer commit."
  exit 1
fi

echo "scan_secrets.sh: sin coincidencias sospechosas."
exit 0
