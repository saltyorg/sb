#!/bin/bash
#shellcheck disable=SC2220
#########################################################################
# Title:         Saltbox sb Re-install Script                           #
# Author(s):     salty                                                  #
# URL:           https://github.com/saltyorg/sb                         #
# --                                                                    #
#########################################################################
#                   GNU General Public License v3.0                     #
#########################################################################

################################
# Variables
################################

SB_REPO="https://github.com/saltyorg/sb.git"
SB_PATH="/srv/git/sb"

################################
# Functions
################################

run_cmd() {
    local cmd_exit_code

    printf '%s\n' "+ $*" >&2;
    "$@"
    cmd_exit_code=$?

    if [ $cmd_exit_code -ne 0 ]; then
        echo "Command failed with exit code $cmd_exit_code: $*" >&2
        exit $cmd_exit_code
    fi
}

################################
# Main
################################

echo "Re-installing sb repository."

# Remove existing repo folder
if [ -d "$SB_PATH" ]; then
    run_cmd rm -rf $SB_PATH;
fi

# Clone SB repo
run_cmd git clone --branch master "${SB_REPO}" "$SB_PATH"

# Set chmod +x on script files
run_cmd chmod +x $SB_PATH/*.sh

## Create script symlinks in /usr/local/bin
shopt -s nullglob
for i in "$SB_PATH"/*.sh; do
    if [ ! -f "/usr/local/bin/$(basename "${i%.*}")" ]; then
        run_cmd ln -s "${i}" "/usr/local/bin/$(basename "${i%.*}")"
    fi
done
shopt -u nullglob
