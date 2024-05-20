#!/bin/bash
#########################################################################
# Title:         Saltbox Repo Cloner Script                             #
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
BRANCH='master'
SALTBOX_PATH="/srv/git/saltbox"
SALTBOX_REPO="https://github.com/saltyorg/saltbox.git"

################################
# Functions
################################

usage () {
    echo "Usage:"
    echo "    sb_repo -b <branch>    Repo branch to use. Default is 'master'."
    echo "    sb_repo -v             Enable Verbose Mode."
    echo "    sb_repo -h             Display this help message."
}

run_cmd() {
    if $VERBOSE; then
        "$@"
    else
        "$@" &>/dev/null
    fi
}

################################
# Argument Parser
################################

while getopts ':b:vh' f; do
    case $f in
    b)  BRANCH=$OPTARG;;
    v)  VERBOSE=true;;
    h)
        usage
        exit 0
        ;;
    \?)
        echo "Invalid Option: -$OPTARG" 1>&2
        echo ""
        usage
        exit 1
        ;;
    esac
done

################################
# Main
################################

$VERBOSE && echo "git branch selected: $BRANCH"

## Clone Saltbox and pull latest commit
if [ -d "$SALTBOX_PATH" ]; then
    if [ -d "$SALTBOX_PATH/.git" ]; then
        cd "$SALTBOX_PATH" || exit
        run_cmd git fetch --all --prune
        # shellcheck disable=SC2086
        run_cmd git checkout -f $BRANCH
        # shellcheck disable=SC2086
        run_cmd git reset --hard origin/$BRANCH
        run_cmd git submodule update --init --recursive
        $VERBOSE && echo "git branch: $(git rev-parse --abbrev-ref HEAD)"
    else
        cd "$SALTBOX_PATH" || exit
        run_cmd rm -rf library/
        run_cmd git init
        run_cmd git remote add origin "$SALTBOX_REPO"
        run_cmd git fetch --all --prune
        # shellcheck disable=SC2086
        run_cmd git branch $BRANCH origin/$BRANCH
        # shellcheck disable=SC2086
        run_cmd git reset --hard origin/$BRANCH
        run_cmd git submodule update --init --recursive
        $VERBOSE && echo "git branch: $(git rev-parse --abbrev-ref HEAD)"
    fi
else
    # shellcheck disable=SC2086
    run_cmd git clone -b $BRANCH "$SALTBOX_REPO" "$SALTBOX_PATH"
    cd "$SALTBOX_PATH" || exit
    run_cmd git submodule update --init --recursive
    $VERBOSE && echo "git branch: $(git rev-parse --abbrev-ref HEAD)"
fi

release=$(lsb_release -cs 2>/dev/null | grep -v "No LSB modules are available.")

## Copy settings and config files into Saltbox folder
shopt -s nullglob
for i in "$SALTBOX_PATH"/defaults/*.default; do
    if [ ! -f "$SALTBOX_PATH/$(basename "${i%.*}")" ]; then
        if [[ $release =~ (focal|jammy)$ ]]; then
            run_cmd cp -n "${i}" "$SALTBOX_PATH/$(basename "${i%.*}")"
        elif [[ $release =~ (noble)$ ]]; then
            run_cmd cp --update=none "${i}" "$SALTBOX_PATH/$(basename "${i%.*}")"
        fi
    fi
done
shopt -u nullglob

## Activate Git Hooks
cd "$SALTBOX_PATH" || exit
run_cmd bash "$SALTBOX_PATH"/bin/git/init-hooks
