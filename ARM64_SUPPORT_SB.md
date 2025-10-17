# ARM64 Support Changes for SB Repository

## Overview
Updated the SB (Saltbox installer) repository to support ARM64 (aarch64) architecture in addition to x86_64.

## Changes Made

### sb_dep.sh

#### Architecture-Aware APT Repository Configuration

**Purpose:** Ensure ARM64 systems use the correct Ubuntu package mirrors.

**Location:** Lines ~116-149

**Issue:** ARM64 systems require `ports.ubuntu.com` instead of `archive.ubuntu.com` for package repositories.

**Solution:** Added architecture detection before configuring APT sources:

```bash
## Detect architecture for proper mirror selection
arch=$(uname -m)
if [[ $arch == "aarch64" ]] || [[ $arch == "arm64" ]]; then
    ubuntu_mirror="http://ports.ubuntu.com/ubuntu-ports"
else
    ubuntu_mirror="http://archive.ubuntu.com/ubuntu"
fi

## Add apt repos
if [[ $release =~ (jammy)$ ]]; then
    sources_file="/etc/apt/sources.list"

    run_cmd rm -rf /etc/apt/sources.list.d/*
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc) main" "$sources_file"
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc) universe" "$sources_file"
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc) restricted" "$sources_file"
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc) multiverse" "$sources_file"

elif [[ $release =~ (noble)$ ]]; then
    sources_file="/etc/apt/sources.list"

    run_cmd find /etc/apt/sources.list.d/ -type f ! -name "ubuntu.sources" -delete
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc) main restricted universe multiverse" "$sources_file"
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc)-updates main restricted universe multiverse" "$sources_file"
    add_repo "deb ${ubuntu_mirror}/ $(lsb_release -sc)-backports main restricted universe multiverse" "$sources_file"
    add_repo "deb ${ubuntu_mirror} $(lsb_release -sc)-security main restricted universe multiverse" "$sources_file"
fi
```

**Impact:**
- **x86_64**: Uses `archive.ubuntu.com` (no change)
- **ARM64**: Uses `ports.ubuntu.com` (fixes APT 404 errors)

### sb_repo.sh

#### Updated Repository URL

**Location:** Line 18

**Changed:** `SALTBOX_REPO` variable to point to testing fork

**Before:**
```bash
SALTBOX_REPO="https://github.com/saltyorg/saltbox.git"
```

**After:**
```bash
SALTBOX_REPO="https://github.com/r3dlobst3r/saltbox.git"
```

**Note:** This should be reverted to `saltyorg/saltbox` before merging to production.

### sb.py

#### Dynamic Branch Detection

**Location:** Lines ~920-945

**Issue:** Script was hardcoded to check `master@{upstream}` when verifying if sb repository needs updating, causing failures when on different branches like `arm_support`.

**Before:**
```python
# Get the current HEAD hash and the upstream master hash
head_hash = subprocess.check_output(
    ['git', 'rev-parse', 'HEAD'],
    cwd=sb_repo_path
).strip()
upstream_hash = subprocess.check_output(
    ['git', 'rev-parse', 'master@{upstream}'],
    cwd=sb_repo_path
).strip()
```

**After:**
```python
# Get the current branch name
current_branch = subprocess.check_output(
    ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
    cwd=sb_repo_path,
    text=True
).strip()

# Get the current HEAD hash and the upstream hash for current branch
head_hash = subprocess.check_output(
    ['git', 'rev-parse', 'HEAD'],
    cwd=sb_repo_path
).strip()
upstream_hash = subprocess.check_output(
    ['git', 'rev-parse', f'{current_branch}@{{upstream}}'],
    cwd=sb_repo_path
).strip()
```

**Impact:**
- Works with any branch (master, arm_support, etc.)
- Dynamically detects current branch before checking upstream
- Fixes "fatal: no such branch: 'master'" error when on non-master branches

### sb_install.sh

#### 1. Architecture Detection (Line ~150)
**Before:**
```bash
if [[ $arch =~ (x86_64)$ ]]; then
    echo "$arch is currently supported."
else
    echo "==== UNSUPPORTED CPU Architecture ===="
    echo "Install cancelled: $arch is not supported."
    echo "Supported CPU Architecture(s): x86_64"
    echo "==== UNSUPPORTED CPU Architecture ===="
    exit 1
fi
```

**After:**
```bash
if [[ $arch =~ (x86_64|aarch64)$ ]]; then
    echo "$arch is currently supported."
else
    echo "==== UNSUPPORTED CPU Architecture ===="
    echo "Install cancelled: $arch is not supported."
    echo "Supported CPU Architecture(s): x86_64, aarch64"
    echo "==== UNSUPPORTED CPU Architecture ===="
    exit 1
fi
```

#### 2. Binary Download Function (Line ~51)
Added architecture-aware binary download logic:

```bash
download_binary() {
    local arch
    local binary_suffix

    # ... existing code ...

    # Determine architecture suffix for binary
    arch=$(uname -m)
    case "$arch" in
        x86_64)
            binary_suffix=""
            ;;
        aarch64)
            binary_suffix="-arm64"
            ;;
        *)
            echo "Error: Unsupported architecture: $arch" >&2
            exit 1
            ;;
    esac

    download_url="https://github.com/saltyorg/sb/releases/download/$version/sb${binary_suffix}"
    
    # ... rest of function ...
}
```

## Binary Naming Convention

The installer now expects the following binary naming in GitHub releases:
- **x86_64**: `sb` (no suffix)
- **ARM64**: `sb-arm64` (with `-arm64` suffix)

## Testing Requirements

Before merging, ensure that:
1. GitHub releases include both `sb` and `sb-arm64` binaries
2. The `sb-arm64` binary is compiled for aarch64 architecture
3. Both binaries are properly signed and tested

## Related Changes

This change is part of the larger ARM64 support effort that includes:
- Main Saltbox repository updates (architecture detection, Docker platform support, binary downloads)
- Documentation updates (README.md, ARM64_SUPPORT.md)
- Role-specific architecture handling

## Impact

- **Users on x86_64**: No change in behavior, continues to download `sb` binary
- **Users on ARM64**: Now able to install Saltbox using `sb-arm64` binary
- **Installation flow**: Automatically detects architecture and downloads correct binary

## Testing Results

### Dependencies Installation (sb_dep.sh)
✅ **Successfully tested on Oracle Cloud ARM64 VPS (Ubuntu 24.04 Noble)**
- Architecture detection works correctly
- APT repositories configured properly with `ports.ubuntu.com`
- All Python dependencies installed successfully
- Virtual environment created and configured

### Repository Cloning (sb_repo.sh)  
- Configuration updated to use r3dlobst3r fork during testing
- Will need revert to saltyorg before production merge

## Known Issues and Fixes

### Issue 1: APT 404 Errors on ARM64
**Problem:** Original code used `archive.ubuntu.com` for all architectures, causing 404 errors on ARM64:
```
E: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-arm64/Packages  404  Not Found
```

**Root Cause:** Ubuntu ARM64 packages are hosted on `ports.ubuntu.com`, not `archive.ubuntu.com`.

**Solution:** Added architecture detection in `sb_dep.sh` to select correct mirror.

**Status:** ✅ Fixed and tested

### Issue 2: Repository Branch Not Found
**Problem:** `sb_repo.sh` tried to clone `arm_support` branch from `saltyorg/saltbox` which doesn't exist.

**Solution:** Updated `SALTBOX_REPO` to point to `r3dlobst3r/saltbox` fork where the branch exists.

**Status:** ✅ Fixed (temporary, needs revert before merge)

### Issue 3: Hardcoded Master Branch Check
**Problem:** `sb.py` was checking for `master@{upstream}` regardless of current branch, causing error:
```
fatal: no such branch: 'master'
Error executing git command: Command '['git', 'rev-parse', 'master@{upstream}']' returned non-zero exit status 128.
```

**Root Cause:** The `check_and_update_repo()` function hardcoded the master branch name instead of detecting the current branch.

**Solution:** Modified `sb.py` to dynamically detect the current branch name and check its upstream.

**Status:** ✅ Fixed

## Future Considerations

1. **Build Pipeline**: ✅ Updated - GitHub Actions now builds both architectures using matrix strategy
2. **Release Process**: ✅ Completed - v1.4.2 includes both `sb` and `sb-arm64` binaries
3. **Testing**: 🔄 In Progress - Validating complete installation flow on ARM64
4. **Documentation**: ✅ ARM64_SUPPORT_SB.md created with comprehensive details
5. **Production Merge**: ⏳ Pending - Need to revert fork references in sb_install.sh, sb_repo.sh before merge
