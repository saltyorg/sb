#!/bin/bash
#shellcheck disable=SC2220
#########################################################################
# Title:         Saltbox Install Script                                 #
# Author(s):     desimaniac, salty                                      #
# URL:           https://github.com/saltyorg/sb                         #
# --                                                                    #
#########################################################################
#                   GNU General Public License v3.0                     #
#########################################################################

################################
# Variables
################################

VERBOSE=false
VERBOSE_OPT=""
SB_REPO="https://github.com/saltyorg/sb.git"
SB_PATH="/srv/git/sb"
SB_INSTALL_SCRIPT="$SB_PATH/sb_install.sh"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
BRANCH="master"

################################
# Functions
################################

run_cmd() {
    local cmd_exit_code

    if $VERBOSE; then
        printf '%s\n' "+ $*" >&2;
        "$@"
        cmd_exit_code=$?
    else
        "$@" > /dev/null 2>&1
        cmd_exit_code=$?
    fi

    if [ $cmd_exit_code -ne 0 ]; then
        echo "Command failed with exit code $cmd_exit_code: $*" >&2
        exit $cmd_exit_code
    fi
}

################################
# Argument Parser
################################

while getopts 'vb:' f; do
  case $f in
  v)  VERBOSE=true
      VERBOSE_OPT="-v"
  ;;
  b)  BRANCH=$OPTARG
  ;;
  esac
done

################################
# Main
################################

# Check if Cloudbox is installed
# develop
if [ -d "/srv/git/cloudbox" ]; then
    echo "==== Cloudbox Install Detected ===="
    echo "Cloudbox installed. Exiting..."
    echo "==== Cloudbox Install Detected ===="
    exit 1
fi

# master
for directory in /home/*/*/ ; do
    base=$(basename "$directory")
    if [ "$base" == "cloudbox" ]; then
        echo "==== Cloudbox Install Detected ===="
        echo "Cloudbox installed. Exiting..."
        echo "==== Cloudbox Install Detected ===="
        exit 1
    fi
done

# Check for supported Ubuntu Releases
release=$(lsb_release -cs 2>/dev/null | grep -v "No LSB modules are available.")

# Add more releases like (focal|jammy)$
if [[ $release =~ (focal|jammy)$ ]]; then
    echo "$release is currently supported."
elif [[ $release =~ (noble)$ ]]; then
    echo "$release is currently in testing."
else
    echo "==== UNSUPPORTED OS ===="
    echo "Install cancelled: $release is not supported."
    echo "Supported OS: 20.04 (focal) and 22.04 (jammy)"
    echo "==== UNSUPPORTED OS ===="
    exit 1
fi

# Check if using valid arch
arch=$(uname -m)

if [[ $arch =~ (x86_64)$ ]]; then
    echo "$arch is currently supported."
else
    echo "==== UNSUPPORTED CPU Architecture ===="
    echo "Install cancelled: $arch is not supported."
    echo "Supported CPU Architecture(s): x86_64"
    echo "==== UNSUPPORTED CPU Architecture ===="
    exit 1
fi

# Check for LXC using systemd-detect-virt
if systemd-detect-virt -c | grep -qi 'lxc'; then
    echo "==== UNSUPPORTED VIRTUALIZATION ===="
    echo "Install cancelled: Running in an LXC container is not supported."
    echo "==== UNSUPPORTED VIRTUALIZATION ===="
    exit 1
fi

# Define required CPU features for x86-64-v2
required_features=("sse4_2" "popcnt")

# Check for x86-64-v2 support
for feature in "${required_features[@]}"; do
  if ! grep -q " $feature " /proc/cpuinfo; then
    echo "==== UNSUPPORTED CPU Microarchitecture ===="
    echo "Error: CPU does not support minimum microarchitecture level: x86-64-v2"
    echo "==== UNSUPPORTED CPU Microarchitecture ===="
    exit 1
  fi
done

echo "Installing Saltbox Dependencies."

$VERBOSE && echo "Script Path: $SCRIPT_PATH"

# Update apt cache
run_cmd apt-get update

# Install git
run_cmd apt-get install -y git

# Remove existing repo folder
if [ -d "$SB_PATH" ]; then
    run_cmd rm -rf $SB_PATH;
fi

# Clone SB repo
run_cmd mkdir -p /srv/git
run_cmd mkdir -p /srv/ansible
run_cmd git clone --branch master "${SB_REPO}" "$SB_PATH"

# Set chmod +x on script files
run_cmd chmod +x $SB_PATH/*.sh

$VERBOSE && echo "Script Path: $SCRIPT_PATH"
$VERBOSE && echo "SB Install Path: "$SB_INSTALL_SCRIPT

## Create script symlinks in /usr/local/bin
shopt -s nullglob
for i in "$SB_PATH"/*.sh; do
    if [ ! -f "/usr/local/bin/$(basename "${i%.*}")" ]; then
        run_cmd ln -s "${i}" "/usr/local/bin/$(basename "${i%.*}")"
    fi
done
shopt -u nullglob

# Install Saltbox Dependencies
run_cmd bash -H $SB_PATH/sb_dep.sh $VERBOSE_OPT

# Clone Saltbox Repo
run_cmd bash -H $SB_PATH/sb_repo.sh -b "${BRANCH}" $VERBOSE_OPT
