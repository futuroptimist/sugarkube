#!/usr/bin/env bash
set -euo pipefail

# Simulate the CI workflow environment locally to catch issues before pushing.
# This script replicates the exact environment and commands used in .github/workflows/ci.yml
# to help identify problems that only manifest in CI (like kcov instrumentation issues).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE}$1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
  echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
  echo -e "${RED}✗ $1${NC}"
}

print_warning() {
  echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
  echo -e "${BLUE}ℹ $1${NC}"
}

# Parse command line arguments
USE_KCOV=false
INSTALL_KCOV=false
KCOV_ONLY=false
SKIP_INSTALL_CHECK=false

usage() {
  cat << EOF
Usage: $0 [OPTIONS]

Simulate CI workflow environment locally to catch issues before pushing.

OPTIONS:
  --with-kcov         Run BATS tests under kcov (like CI does)
  --install-kcov      Install kcov if not present (requires sudo)
  --kcov-only         Only run kcov simulation, skip basic tests
  --skip-install      Skip checking for missing dependencies
  -h, --help          Show this help message

EXAMPLES:
  # Basic simulation (BATS tests + pytest)
  $0

  # Full CI simulation with kcov (requires kcov to be installed)
  $0 --with-kcov

  # Install kcov and run full simulation
  $0 --install-kcov --with-kcov

NOTES:
  - Basic mode runs both BATS and pytest tests (matching CI workflow)
  - pytest requires: pip install pytest pytest-cov
  - BATS tests set BATS_CWD and BATS_LIB_PATH like CI does
  - kcov mode runs BATS tests under code coverage (catches instrumentation issues)
  - Installing kcov requires sudo and takes ~2-3 minutes

EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --with-kcov)
      USE_KCOV=true
      shift
      ;;
    --install-kcov)
      INSTALL_KCOV=true
      shift
      ;;
    --kcov-only)
      KCOV_ONLY=true
      USE_KCOV=true
      shift
      ;;
    --skip-install)
      SKIP_INSTALL_CHECK=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

print_header "CI Workflow Simulation"
echo "Working directory: $ROOT_DIR"
echo "Mode: $([ "$USE_KCOV" = true ] && echo "with kcov" || echo "basic")"
echo ""

# Check for required tools
check_dependencies() {
  local missing=()
  
  if ! command -v bats >/dev/null 2>&1; then
    missing+=("bats")
  fi
  
  if ! command -v python3 >/dev/null 2>&1; then
    missing+=("python3")
  fi
  
  if [ "$USE_KCOV" = true ] && ! command -v kcov >/dev/null 2>&1; then
    if [ "$INSTALL_KCOV" = false ]; then
      print_warning "kcov not found. Use --install-kcov to install it."
      return 1
    fi
  fi
  
  if [ ${#missing[@]} -gt 0 ]; then
    print_error "Missing required tools: ${missing[*]}"
    echo "Install with:"
    echo "  sudo apt-get install ${missing[*]}"
    return 1
  fi
  
  # Check for pytest
  if ! python3 -m pytest --version >/dev/null 2>&1; then
    print_warning "pytest not found. Install with: pip install pytest pytest-cov"
    print_info "Python tests will be skipped"
    return 0  # Don't fail, just warn
  fi
  
  return 0
}

install_kcov() {
  print_header "Installing kcov"
  
  if command -v kcov >/dev/null 2>&1; then
    print_info "kcov already installed at $(which kcov)"
    kcov --version || true
    return 0
  fi
  
  print_info "Cloning kcov repository..."
  local temp_dir
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT
  
  cd "$temp_dir"
  git clone --depth=1 https://github.com/SimonKagstrom/kcov.git
  cd kcov
  
  print_info "Building kcov (this may take 2-3 minutes)..."
  cmake -B build
  cmake --build build
  
  print_info "Installing kcov (requires sudo)..."
  sudo cmake --install build
  
  cd "$ROOT_DIR"
  
  if command -v kcov >/dev/null 2>&1; then
    print_success "kcov installed successfully"
    kcov --version
  else
    print_error "kcov installation failed"
    return 1
  fi
}


validate_test_patterns() {
  print_header "Validating Test Patterns"
  
  local issues_found=0
  
  # Check if summary.sh has EXIT trap disabled by default
  print_info "Checking summary.sh EXIT trap handling..."
  
  if grep -q 'SUMMARY_AUTO_EMIT' scripts/lib/summary.sh; then
    print_success "summary.sh uses opt-in EXIT trap (SUMMARY_AUTO_EMIT)"
  else
    print_warning "summary.sh may not have proper EXIT trap control"
    print_info "  EXIT traps should be opt-in to avoid kcov issues"
    ((issues_found++)) || true
  fi
  
  # Check if BATS tests using summary.sh call emit explicitly
  print_info "Checking for explicit summary::emit calls in tests..."
  
  local test_files
  mapfile -t test_files < <(find tests/bats -name "*.bats" -type f 2>/dev/null)
  
  for file in "${test_files[@]}"; do
    if grep -q 'source.*summary\.sh' "$file" 2>/dev/null; then
      # Check if test calls emit explicitly
      if ! grep -q 'summary::emit' "$file" 2>/dev/null; then
        print_warning "File $file: Uses summary.sh but no explicit summary::emit"
        print_info "  Should call summary::emit explicitly (EXIT trap disabled by default)"
        ((issues_found++)) || true
      fi
    fi
  done
  
  if [ "$issues_found" -eq 0 ]; then
    print_success "All test patterns validated"
    return 0
  else
    print_warning "Found $issues_found potential issue(s)"
    print_info "Recommendation: BATS tests using summary.sh should:"
    echo "    1. Call summary::emit explicitly (EXIT trap opt-in only)"
    echo "    2. Don't rely on EXIT trap for tests (disabled by default)"
    echo "    3. Production scripts can use SUMMARY_AUTO_EMIT=1 if needed"
    return 0  # Warning, not error
  fi
}

run_basic_simulation() {
  print_header "Running Basic CI Simulation"
  
  # Set environment variables exactly as CI does
  export BATS_CWD="${ROOT_DIR}"
  export BATS_LIB_PATH="${ROOT_DIR}/tests/bats"
  
  print_info "Environment variables set:"
  echo "  BATS_CWD=$BATS_CWD"
  echo "  BATS_LIB_PATH=$BATS_LIB_PATH"
  echo ""
  
  print_info "Running: bats --recursive tests/bats"
  echo ""
  
  if bats --recursive tests/bats; then
    print_success "BATS tests passed in CI-simulated environment"
    return 0
  else
    print_error "BATS tests failed in CI-simulated environment"
    return 1
  fi
}

run_pytest_simulation() {
  print_header "Running pytest CI Simulation"
  
  # Check if pytest is available
  if ! python3 -m pytest --version >/dev/null 2>&1; then
    print_warning "pytest not available - skipping Python tests"
    print_info "Install with: pip install pytest pytest-cov"
    return 0  # Don't fail if pytest is missing
  fi
  
  print_info "Python version: $(python3 --version)"
  echo ""
  
  # Discover test files (exclude test_qemu_pi_smoke_test.py like ci_commands.sh does)
  local -a pytest_targets
  mapfile -t pytest_targets < <(find tests -name 'test_*.py' ! -name 'test_qemu_pi_smoke_test.py' -print | LC_ALL=C sort)
  
  if [ "${#pytest_targets[@]}" -eq 0 ]; then
    print_error "No pytest targets discovered"
    return 1
  fi
  
  print_info "Running pytest on ${#pytest_targets[@]} test files..."
  echo "Command:"
  echo "  pytest -q <${#pytest_targets[@]} test files>"
  echo ""
  
  if pytest -q "${pytest_targets[@]}"; then
    print_success "Python tests passed (${#pytest_targets[@]} test files)"
    
    # Note about coverage
    print_info ""
    print_info "Note: Running without coverage for speed. CI runs with coverage:"
    echo "  pytest -q --cov=scripts --cov=tests --cov-report=xml:coverage/python-coverage.xml"
    
    return 0
  else
    print_error "Python tests failed"
    print_warning "This indicates an issue that would fail in CI!"
    print_info "Note: CI may run a different Python version than local environment"
    print_info "Check for:"
    echo "  - Python version compatibility issues"
    echo "  - Import path problems (sys.path configuration)"
    echo "  - Test fixture issues"
    return 1
  fi
}

run_kcov_simulation() {
  print_header "Running kcov CI Simulation"
  
  if ! command -v kcov >/dev/null 2>&1; then
    print_error "kcov not found. Install it first with --install-kcov"
    return 1
  fi
  
  # Set environment variables exactly as CI does
  export KCOV_OUT="${ROOT_DIR}/coverage/kcov"
  export BATS_CWD="${ROOT_DIR}"
  export BATS_LIB_PATH="${ROOT_DIR}/tests/bats"
  
  print_info "Environment variables set:"
  echo "  KCOV_OUT=$KCOV_OUT"
  echo "  BATS_CWD=$BATS_CWD"
  echo "  BATS_LIB_PATH=$BATS_LIB_PATH"
  echo ""
  
  mkdir -p "$KCOV_OUT"
  
  print_info "Running BATS under kcov (exactly as CI does)..."
  echo "Command:"
  echo "  kcov --include-path=\"${ROOT_DIR}/scripts\" \\"
  echo "       --exclude-pattern=\"/usr,/opt,/lib,/bin,/sbin,${ROOT_DIR}/tests\" \\"
  echo "       --bash-dont-parse-binary-dir \\"
  echo "       \"$KCOV_OUT\" \\"
  echo "       bats --recursive tests/bats"
  echo ""
  
  if kcov --include-path="${ROOT_DIR}/scripts" \
          --exclude-pattern="/usr,/opt,/lib,/bin,/sbin,${ROOT_DIR}/tests" \
          --bash-dont-parse-binary-dir \
          "$KCOV_OUT" \
          bats --recursive tests/bats; then
    print_success "BATS tests passed under kcov instrumentation"
    print_info "Coverage report: $KCOV_OUT/index.html"
    return 0
  else
    print_error "BATS tests failed under kcov instrumentation"
    print_warning "This indicates an issue that would fail in CI!"
    print_info "Check for:"
    echo "  - EXIT trap issues with kcov"
    echo "  - Subshell depth problems"
    echo "  - Exit status propagation issues"
    return 1
  fi
}

# Main execution
main() {
  local exit_code=0
  
  # Validate test patterns first
  validate_test_patterns
  echo ""
  
  if [ "$SKIP_INSTALL_CHECK" = false ]; then
    if ! check_dependencies; then
      exit 1
    fi
  fi
  
  if [ "$INSTALL_KCOV" = true ]; then
    if ! install_kcov; then
      exit 1
    fi
  fi
  
  if [ "$KCOV_ONLY" = false ]; then
    # Run BATS tests
    if ! run_basic_simulation; then
      exit_code=1
    fi
    echo ""
    
    # Run pytest tests
    if ! run_pytest_simulation; then
      exit_code=1
    fi
    echo ""
  fi
  
  if [ "$USE_KCOV" = true ]; then
    if ! run_kcov_simulation; then
      exit_code=1
    fi
    echo ""
  fi
  
  print_header "Summary"
  if [ $exit_code -eq 0 ]; then
    print_success "All CI simulations passed!"
    echo ""
    print_info "Your changes should pass in CI ✓"
  else
    print_error "CI simulation failed!"
    echo ""
    print_warning "Fix the issues above before pushing to avoid CI failures"
  fi
  
  return $exit_code
}

main
