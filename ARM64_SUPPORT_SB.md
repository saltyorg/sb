# ARM64 Support Changes for SB Repository

## Overview
Updated the SB (Saltbox installer) repository to support ARM64 (aarch64) architecture in addition to x86_64.

## Changes Made

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

## Future Considerations

1. **Build Pipeline**: CI/CD should be updated to build both x86_64 and ARM64 binaries
2. **Release Process**: Both binaries should be included in each release
3. **Testing**: Automated tests should validate both architectures
4. **Documentation**: Update sb repository README to mention ARM64 support
